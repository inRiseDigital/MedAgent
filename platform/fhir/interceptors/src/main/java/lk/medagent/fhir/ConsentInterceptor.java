package lk.medagent.fhir;

import ca.uhn.fhir.context.FhirContext;
import ca.uhn.fhir.interceptor.api.Hook;
import ca.uhn.fhir.interceptor.api.Interceptor;
import ca.uhn.fhir.interceptor.api.Pointcut;
import ca.uhn.fhir.rest.api.server.IPreResourceShowDetails;
import ca.uhn.fhir.rest.api.server.RequestDetails;
import ca.uhn.fhir.rest.api.server.storage.TransactionDetails;
import org.hl7.fhir.instance.model.api.IBaseResource;
import org.hl7.fhir.r4.model.Bundle;
import org.hl7.fhir.r4.model.CodeableConcept;
import org.hl7.fhir.r4.model.Coding;
import org.hl7.fhir.r4.model.Consent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * Consent interceptor — second stage of the MedAgent pipeline
 * (docs/solution/03 §2, §5.2; spec §4.3 "consent manager enforces at runtime").
 *
 * <p>Runtime evaluation of a resource's subject Consent: on show, resolve the
 * subject Patient, fetch that patient's active {@code Consent} (over the server's
 * own REST endpoint, presenting the trusted-service credential), and if the patient
 * has an active consent whose root {@code provision.type = deny} — they have
 * withdrawn sharing — MASK the resource, unless the access is break-glass
 * (purposeOfUse = BTG). Verdicts are cached per request (one lookup per patient).
 *
 * <p><b>Per-purpose sharing:</b> a deny provision may be scoped to a
 * {@code provision.purpose} PurposeOfUse code (e.g. TREAT / HRESCH / HMARKT). A
 * purpose-scoped deny masks only when the request's own purpose (the
 * {@code X-MedAgent-Purpose} header, else the stamped {@link
 * AuthzInterceptor#CTX_PURPOSE_OF_USE}, else {@link #DEFAULT_PURPOSE}) matches one
 * of the deny's purposes. A deny with NO purpose is a global record-sharing
 * withdrawal and masks every purpose (back-compat with the single-toggle model).
 * Crucially this only ever ADDS conditions to masking: a purpose-scoped deny that
 * does not match the request's purpose never masks a read that flows today.
 *
 * <p><b>Safety posture:</b> Authz is the fail-closed primary gate; consent is a
 * second, additive restriction. On an evaluation error this layer logs loudly and
 * passes (never denies legitimate treatment on a consent-eval bug); it only masks on
 * a clear active deny. Without a configured FHIR base (unit tests) it is a no-op
 * pass-through. Redis verdict caching + event-driven invalidation (03 §5.2) remain a
 * follow-up; today it evaluates live.
 */
@Interceptor
public class ConsentInterceptor {

    private static final Logger ourLog = LoggerFactory.getLogger(ConsentInterceptor.class);

    static final String CACHE_KEY_TEMPLATE = "consent:%s:%s:%s"; // patient, purpose, actorClass
    private static final String REQ_CACHE = "medagent.consent.verdicts";
    static final String SERVICE_KEY_HEADER = "X-MedAgent-Service-Key";
    static final String PURPOSE_HEADER = "X-MedAgent-Purpose";
    static final String FHIR_BASE_ENV = "MEDAGENT_FHIR_BASE";
    static final String SERVICE_KEY_ENV = "MEDAGENT_SERVICE_KEY";

    /** The purpose of a request that carries no explicit purpose — a normal
     *  treatment read. Chosen so the per-purpose logic degrades to today's
     *  behaviour when no purpose is forwarded (fail-safe: never newly masks). */
    static final String DEFAULT_PURPOSE = "TREAT";

    private final String myFhirBase;
    private final String myServiceKey;
    private final HttpClient myHttp;
    private final FhirContext myCtx = FhirContext.forR4();

    public ConsentInterceptor() {
        this(env(FHIR_BASE_ENV, "http://localhost:8080/fhir"), env(SERVICE_KEY_ENV, ""));
    }

    ConsentInterceptor(String theFhirBase, String theServiceKey) {
        myFhirBase = theFhirBase == null ? "" : theFhirBase.replaceAll("/+$", "");
        myServiceKey = theServiceKey == null ? "" : theServiceKey;
        myHttp = myFhirBase.isEmpty() ? null
                : HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
        ourLog.info("ConsentInterceptor: {} (base={})",
                myHttp == null ? "PASS-THROUGH (no base)" : "EVALUATE (REST)", myFhirBase);
    }

    /** Mask any shown resource whose subject has an active deny-consent (unless BTG). */
    @Hook(Pointcut.STORAGE_PRESHOW_RESOURCES)
    public void applyConsentToShownResources(IPreResourceShowDetails theShowDetails, RequestDetails theRequestDetails) {
        if (myHttp == null || theShowDetails == null) {
            return;
        }
        String purpose = requestPurpose(theRequestDetails);
        if ("BTG".equals(purpose)) {
            return; // break-glass overrides deny-by-consent (03 §5.2)
        }
        for (int i = 0; i < theShowDetails.size(); i++) {
            try {
                IBaseResource resource = theShowDetails.getResource(i);
                String patientId = subjectPatientId(resource);
                if (patientId != null && isDenied(patientId, purpose, theRequestDetails)) {
                    theShowDetails.setResource(i, null);
                    ourLog.info("medagent-consent: masked {} (subject Patient/{} has active deny-consent for purpose {})",
                            resource.fhirType(), patientId, purpose);
                }
            } catch (RuntimeException e) {
                ourLog.error("medagent-consent: evaluation error — passing (authz already gated)", e);
            }
        }
    }

    /**
     * The purpose of use backing this request, upper-cased. Prefers the forwarded
     * {@code X-MedAgent-Purpose} header (the fine-grained value: TREAT / HRESCH /
     * HMARKT / BTG …), then the purpose the {@link AuthzInterceptor} stamped into the
     * request context, and finally {@link #DEFAULT_PURPOSE}. Defaulting to TREAT is
     * what keeps this fail-safe: an unlabelled read is treated as a treatment read,
     * so a purpose-scoped deny for some OTHER purpose can never mask it.
     */
    String requestPurpose(RequestDetails theRequestDetails) {
        if (theRequestDetails == null) {
            return DEFAULT_PURPOSE;
        }
        String header = theRequestDetails.getHeader(PURPOSE_HEADER);
        if (header != null && !header.isBlank()) {
            return header.trim().toUpperCase(Locale.ROOT);
        }
        Object ctx = theRequestDetails.getUserData().get(AuthzInterceptor.CTX_PURPOSE_OF_USE);
        if (ctx != null && !String.valueOf(ctx).isBlank()) {
            return String.valueOf(ctx).toUpperCase(Locale.ROOT);
        }
        return DEFAULT_PURPOSE;
    }

    /** True if this patient has an active Consent whose provision denies sharing for
     *  {@code theRequestPurpose} (a purpose-less deny denies every purpose). */
    boolean isDenied(String thePatientId, String theRequestPurpose, RequestDetails theRequestDetails) {
        Map<String, Boolean> cache = requestCache(theRequestDetails);
        Boolean cached = cache == null ? null : cache.get(thePatientId);
        if (cached != null) {
            return cached;
        }
        boolean denied = false;
        try {
            String url = myFhirBase + "/Consent?status=active&patient="
                    + URLEncoder.encode("Patient/" + thePatientId, StandardCharsets.UTF_8) + "&_count=20";
            HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(url))
                    .timeout(Duration.ofSeconds(6)).header("Accept", "application/fhir+json").GET();
            if (!myServiceKey.isEmpty()) {
                b.header(SERVICE_KEY_HEADER, myServiceKey);
                b.header("X-MedAgent-Roles", "system");
                b.header("X-MedAgent-Purpose", "TREAT");
            }
            HttpResponse<String> resp = myHttp.send(b.build(), HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() < 300 && resp.body() != null && !resp.body().isBlank()) {
                Bundle bundle = myCtx.newJsonParser().parseResource(Bundle.class, resp.body());
                for (Bundle.BundleEntryComponent e : bundle.getEntry()) {
                    if (e.getResource() instanceof Consent c
                            && c.hasProvision()
                            && c.getProvision().getType() == Consent.ConsentProvisionType.DENY
                            && isRecordSharingConsent(c)
                            && deniesForPurpose(c, theRequestPurpose)) {
                        // A withdrawal of RECORD sharing — not a biometric/face-recognition
                        // consent (which governs kiosk check-in, not FHIR visibility) — that
                        // applies to THIS request's purpose (or is a global, purpose-less deny).
                        denied = true;
                        break;
                    }
                }
            }
        } catch (Exception e) {
            ourLog.error("medagent-consent: Consent lookup failed for Patient/{} — passing", thePatientId, e);
            denied = false; // fail-open at the consent layer (authz is the hard gate)
        }
        if (cache != null) {
            cache.put(thePatientId, denied);
        }
        return denied;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Boolean> requestCache(RequestDetails theRequestDetails) {
        if (theRequestDetails == null) {
            return null;
        }
        Object existing = theRequestDetails.getUserData().get(REQ_CACHE);
        if (existing instanceof Map) {
            return (Map<String, Boolean>) existing;
        }
        Map<String, Boolean> fresh = new HashMap<>();
        theRequestDetails.getUserData().put(REQ_CACHE, fresh);
        return fresh;
    }

    /** The subject Patient logical id for a resource, or null if it isn't patient-scoped. */
    static String subjectPatientId(IBaseResource theResource) {
        if (theResource == null) {
            return null;
        }
        String ref = null;
        if (theResource instanceof org.hl7.fhir.r4.model.Observation o && o.hasSubject()) {
            ref = o.getSubject().getReference();
        } else if (theResource instanceof org.hl7.fhir.r4.model.Condition c && c.hasSubject()) {
            ref = c.getSubject().getReference();
        } else if (theResource instanceof org.hl7.fhir.r4.model.MedicationRequest m && m.hasSubject()) {
            ref = m.getSubject().getReference();
        } else if (theResource instanceof org.hl7.fhir.r4.model.AllergyIntolerance a && a.hasPatient()) {
            ref = a.getPatient().getReference();
        } else if (theResource instanceof org.hl7.fhir.r4.model.DiagnosticReport d && d.hasSubject()) {
            ref = d.getSubject().getReference();
        } else if (theResource instanceof org.hl7.fhir.r4.model.Immunization im && im.hasPatient()) {
            ref = im.getPatient().getReference();
        } else if (theResource instanceof org.hl7.fhir.r4.model.Encounter en && en.hasSubject()) {
            ref = en.getSubject().getReference();
        } else if (theResource instanceof org.hl7.fhir.r4.model.Procedure pr && pr.hasSubject()) {
            ref = pr.getSubject().getReference();
        } else if (theResource instanceof org.hl7.fhir.r4.model.Patient p) {
            return p.getIdElement().getIdPart();
        }
        if (ref != null && ref.toLowerCase(Locale.ROOT).startsWith("patient/")) {
            return ref.substring("patient/".length());
        }
        return null;
    }

    // --- cache-invalidation triggers (Redis pub/sub is a follow-up) ------------
    @Hook(Pointcut.STORAGE_PRECOMMIT_RESOURCE_CREATED)
    public void onConsentCreated(IBaseResource theResource, RequestDetails theRequestDetails,
                                 TransactionDetails theTransactionDetails) {
        if (isConsent(theResource)) {
            ourLog.debug("medagent-consent: Consent created — request-scoped eval, no external cache to invalidate yet");
        }
    }

    @Hook(Pointcut.STORAGE_PRECOMMIT_RESOURCE_UPDATED)
    public void onConsentUpdated(IBaseResource theOldResource, IBaseResource theNewResource,
                                 RequestDetails theRequestDetails, TransactionDetails theTransactionDetails) {
        if (isConsent(theNewResource)) {
            ourLog.debug("medagent-consent: Consent updated — request-scoped eval, no external cache to invalidate yet");
        }
    }

    static boolean isConsent(IBaseResource theResource) {
        return theResource != null && "Consent".equals(theResource.fhirType());
    }

    /** Category codes that are NOT about FHIR record visibility (they govern other
     *  things — e.g. biometric check-in) and must never mask clinical resources. */
    private static final java.util.Set<String> NON_SHARING_CATEGORIES = java.util.Set.of("face-recognition");

    /** True if a deny-consent actually withdraws RECORD sharing (vs. a biometric /
     *  reminder-channel consent that happens to use provision.type=deny). */
    static boolean isRecordSharingConsent(Consent theConsent) {
        for (CodeableConcept cat : theConsent.getCategory()) {
            for (Coding coding : cat.getCoding()) {
                String code = coding.getCode();
                if (code != null && NON_SHARING_CATEGORIES.contains(code.toLowerCase(Locale.ROOT))) {
                    return false; // e.g. face-recognition — governs check-in, not record visibility
                }
            }
        }
        return true;
    }

    /**
     * Whether a record-sharing DENY consent applies to a request made for
     * {@code theRequestPurpose}.
     *
     * <p><b>Back-compat / fail-safe contract:</b>
     * <ul>
     *   <li>A deny with NO {@code provision.purpose} is a <em>global</em> withdrawal
     *       of record sharing (the original single-toggle model) — it applies to
     *       every purpose, exactly as before.</li>
     *   <li>A deny scoped to one or more purposes applies ONLY when the request's
     *       purpose is one of them. A purpose-scoped deny for some other purpose
     *       therefore never masks a read that flows today — adding a per-purpose
     *       deny can only add masking for its own purpose, never remove or broaden it.</li>
     * </ul>
     */
    static boolean deniesForPurpose(Consent theConsent, String theRequestPurpose) {
        Set<String> purposes = provisionPurposeCodes(theConsent);
        if (purposes.isEmpty()) {
            return true; // global record-sharing deny — applies to all purposes (back-compat)
        }
        return theRequestPurpose != null
                && purposes.contains(theRequestPurpose.toUpperCase(Locale.ROOT));
    }

    /** The PurposeOfUse codes on a consent's root provision (upper-cased), or empty
     *  for an unscoped (global) deny. */
    static Set<String> provisionPurposeCodes(Consent theConsent) {
        Set<String> codes = new HashSet<>();
        if (theConsent.hasProvision()) {
            for (Coding coding : theConsent.getProvision().getPurpose()) {
                String code = coding.getCode();
                if (code != null && !code.isBlank()) {
                    codes.add(code.toUpperCase(Locale.ROOT));
                }
            }
        }
        return codes;
    }

    private static String env(String key, String def) {
        String v = System.getenv(key);
        return v == null ? def : v;
    }
}
