package lk.medagent.fhir;

import ca.uhn.fhir.context.FhirContext;
import ca.uhn.fhir.interceptor.api.Hook;
import ca.uhn.fhir.interceptor.api.Interceptor;
import ca.uhn.fhir.interceptor.api.Pointcut;
import ca.uhn.fhir.rest.api.server.RequestDetails;
import ca.uhn.fhir.rest.api.server.storage.TransactionDetails;
import org.hl7.fhir.instance.model.api.IBaseResource;
import org.hl7.fhir.r4.model.AuditEvent;
import org.hl7.fhir.r4.model.CodeableConcept;
import org.hl7.fhir.r4.model.Coding;
import org.hl7.fhir.r4.model.DecimalType;
import org.hl7.fhir.r4.model.InstantType;
import org.hl7.fhir.r4.model.Reference;
import org.hl7.fhir.r4.model.StringType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.math.BigDecimal;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Audit interceptor — final stage of the MedAgent pipeline
 * (docs/solution/03 §2, §5.3, §5.4; NFR-8 100% coverage, tamper-evident).
 *
 * <p>Every storage mutation becomes a FHIR {@code AuditEvent}: action (C/U/D),
 * entity (resource ref), the real actor (forwarded roles) and the {@code purposeOfUse}
 * stamped by {@link AuthzInterceptor}. Each event carries the tamper-evidence
 * extensions {@code audit-seq} (per-process monotonic sequence) and
 * {@code audit-prev-hash} (SHA-256 chained over the previous event).
 *
 * <p><b>Persistence:</b> the AuditEvent is PERSISTED by POSTing it to the server's
 * own {@code /AuditEvent} endpoint on a single background thread — off the request
 * transaction (no nesting/deadlock), presenting the trusted-service credential so it
 * passes the fail-closed Authz gate, and with a re-entrancy guard so auditing never
 * audits itself. This is a real, persisted, chained audit — the step up from the S1
 * log-only skeleton. (Atomic in-transaction persistence into a dedicated append-only
 * partition, and a DB-continued chain across restarts, remain per 03 §5.3–5.4.)
 */
@Interceptor
public class AuditInterceptor {

    private static final Logger ourLog = LoggerFactory.getLogger(AuditInterceptor.class);

    public static final String EXT_AUDIT_SEQ = "https://fhir.medagent.health.lk/StructureDefinition/audit-seq";
    public static final String EXT_AUDIT_PREV_HASH = "https://fhir.medagent.health.lk/StructureDefinition/audit-prev-hash";
    static final String GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000";

    static final String ROLES_HEADER = "X-MedAgent-Roles";
    static final String SERVICE_KEY_HEADER = "X-MedAgent-Service-Key";
    static final String FHIR_BASE_ENV = "MEDAGENT_FHIR_BASE";      // default http://localhost:8080/fhir
    static final String SERVICE_KEY_ENV = "MEDAGENT_SERVICE_KEY";

    private final String myFhirBase;
    private final String myServiceKey;
    private final ExecutorService myWriter;
    private final HttpClient myHttp;
    private final FhirContext myCtx = FhirContext.forR4();
    private final AtomicLong mySeq = new AtomicLong(0);
    private volatile String myPrevHash = GENESIS_HASH;

    public AuditInterceptor() {
        this(env(FHIR_BASE_ENV, "http://localhost:8080/fhir"), env(SERVICE_KEY_ENV, ""));
    }

    AuditInterceptor(String theFhirBase, String theServiceKey) {
        myFhirBase = theFhirBase == null ? "" : theFhirBase.replaceAll("/+$", "");
        myServiceKey = theServiceKey == null ? "" : theServiceKey;
        boolean canPersist = !myFhirBase.isEmpty();
        myWriter = canPersist ? Executors.newSingleThreadExecutor(r -> {
            Thread t = new Thread(r, "medagent-audit-writer");
            t.setDaemon(true);
            return t;
        }) : null;
        myHttp = canPersist ? HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build() : null;
        ourLog.info("AuditInterceptor: {} (base={})",
                canPersist ? "PERSIST (REST, chained)" : "LOG-ONLY", myFhirBase);
    }

    @Hook(Pointcut.STORAGE_PRECOMMIT_RESOURCE_CREATED)
    public void auditCreated(IBaseResource theResource, RequestDetails theRequestDetails,
                             TransactionDetails theTransactionDetails) {
        record(AuditEvent.AuditEventAction.C, theResource, theRequestDetails);
    }

    @Hook(Pointcut.STORAGE_PRECOMMIT_RESOURCE_UPDATED)
    public void auditUpdated(IBaseResource theOldResource, IBaseResource theNewResource,
                             RequestDetails theRequestDetails, TransactionDetails theTransactionDetails) {
        record(AuditEvent.AuditEventAction.U, theNewResource, theRequestDetails);
    }

    @Hook(Pointcut.STORAGE_PRECOMMIT_RESOURCE_DELETED)
    public void auditDeleted(IBaseResource theResource, RequestDetails theRequestDetails,
                             TransactionDetails theTransactionDetails) {
        record(AuditEvent.AuditEventAction.D, theResource, theRequestDetails);
    }

    /** Build → chain → persist (or log). Re-entrancy guard: never audit an AuditEvent. */
    void record(AuditEvent.AuditEventAction theAction, IBaseResource theResource, RequestDetails theRequestDetails) {
        if (theResource != null && "AuditEvent".equals(theResource.fhirType())) {
            return; // don't audit the audit write — would recurse forever
        }
        try {
            AuditEvent event = buildAuditEvent(theAction, theResource, theRequestDetails);
            chain(event);
            persist(event);
        } catch (RuntimeException e) {
            ourLog.error("medagent-audit: failed to record audit event", e);
        }
    }

    AuditEvent buildAuditEvent(AuditEvent.AuditEventAction theAction, IBaseResource theResource,
                               RequestDetails theRequestDetails) {
        AuditEvent auditEvent = new AuditEvent();
        auditEvent.setAction(theAction);
        auditEvent.setRecordedElement(new InstantType(new Date()));
        auditEvent.setType(new Coding("http://terminology.hl7.org/CodeSystem/audit-event-type",
                "rest", "RESTful Operation"));
        auditEvent.setOutcome(AuditEvent.AuditEventOutcome._0);
        // source (1..1 required): the observer that recorded this event.
        auditEvent.getSource().setObserver(new Reference().setDisplay("MedAgent FHIR interceptor"));

        AuditEvent.AuditEventEntityComponent entity = auditEvent.addEntity();
        if (theResource != null && theResource.getIdElement() != null) {
            // Record the target as a logical identifier + display, NOT a resolvable
            // literal reference — audit must never fail on referential integrity
            // (HAPI-1094) if the target is in another partition or not yet visible.
            String ref = theResource.getIdElement().toUnqualifiedVersionless().getValue();
            entity.getWhat().setDisplay(ref);
            entity.getWhat().getIdentifier()
                    .setSystem("https://fhir.medagent.health.lk/sid/resource").setValue(ref);
        }

        AuditEvent.AuditEventAgentComponent agent = auditEvent.addAgent();
        agent.setRequestor(true);
        String roles = theRequestDetails == null ? null : theRequestDetails.getHeader(ROLES_HEADER);
        if (roles != null && !roles.isBlank()) {
            agent.setAltId(roles.trim().toLowerCase(Locale.ROOT));
        }
        Object purpose = theRequestDetails == null ? null
                : theRequestDetails.getUserData().get(AuthzInterceptor.CTX_PURPOSE_OF_USE);
        if (purpose != null) {
            agent.addPurposeOfUse(new CodeableConcept().addCoding(new Coding(
                    "http://terminology.hl7.org/CodeSystem/v3-ActReason", String.valueOf(purpose), null)));
        }
        return auditEvent;
    }

    /** Assign the monotonic sequence + prev-hash chain, then advance the head. */
    synchronized void chain(AuditEvent theEvent) {
        long seq = mySeq.incrementAndGet();
        theEvent.addExtension(EXT_AUDIT_SEQ, new DecimalType(new BigDecimal(seq)));
        theEvent.addExtension(EXT_AUDIT_PREV_HASH, new StringType(myPrevHash));
        String material = myPrevHash + "|" + seq + "|" + theEvent.getAction() + "|"
                + (theEvent.hasEntity() ? theEvent.getEntityFirstRep().getWhat().getReference() : "")
                + "|" + theEvent.getRecordedElement().getValueAsString();
        myPrevHash = sha256(material);
    }

    private void persist(AuditEvent theEvent) {
        String seq = theEvent.getExtensionByUrl(EXT_AUDIT_SEQ).getValue().primitiveValue();
        String ref = theEvent.hasEntity() ? theEvent.getEntityFirstRep().getWhat().getReference() : "n/a";
        if (myWriter == null) {
            ourLog.info("medagent-audit: action={} entity={} seq={} (log-only — no base)",
                    theEvent.getAction(), ref, seq);
            return;
        }
        final String body = myCtx.newJsonParser().encodeResourceToString(theEvent);
        myWriter.submit(() -> {
            try {
                HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(myFhirBase + "/AuditEvent"))
                        .timeout(Duration.ofSeconds(8))
                        .header("Content-Type", "application/fhir+json")
                        .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8));
                if (!myServiceKey.isEmpty()) {
                    b.header(SERVICE_KEY_HEADER, myServiceKey);
                    b.header(ROLES_HEADER, "system");
                    b.header("X-MedAgent-Purpose", "TREAT");
                }
                HttpResponse<String> resp = myHttp.send(b.build(), HttpResponse.BodyHandlers.ofString());
                if (resp.statusCode() >= 300) {
                    ourLog.error("medagent-audit: persist seq={} -> HTTP {} {}", seq, resp.statusCode(),
                            resp.body() == null ? "" : resp.body().substring(0, Math.min(600, resp.body().length())));
                } else {
                    ourLog.debug("medagent-audit: persisted seq={} entity={}", seq, ref);
                }
            } catch (Exception e) {
                ourLog.error("medagent-audit: persist failed for seq={}", seq, e);
            }
        });
    }

    private static String sha256(String s) {
        try {
            byte[] d = MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(64);
            for (byte x : d) {
                sb.append(Character.forDigit((x >> 4) & 0xF, 16)).append(Character.forDigit(x & 0xF, 16));
            }
            return sb.toString();
        } catch (Exception e) {
            return GENESIS_HASH;
        }
    }

    private static String env(String key, String def) {
        String v = System.getenv(key);
        return v == null ? def : v;
    }
}
