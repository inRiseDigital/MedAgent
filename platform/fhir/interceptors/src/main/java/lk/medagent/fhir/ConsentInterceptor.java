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
import java.util.Locale;
import java.util.Map;

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
    static final String FHIR_BASE_ENV = "MEDAGENT_FHIR_BASE";
    static final String SERVICE_KEY_ENV = "MEDAGENT_SERVICE_KEY";

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
        Object purpose = theRequestDetails == null ? null
                : theRequestDetails.getUserData().get(AuthzInterceptor.CTX_PURPOSE_OF_USE);
        if ("BTG".equalsIgnoreCase(String.valueOf(purpose))) {
            return; // break-glass overrides deny-by-consent (03 §5.2)
        }
        for (int i = 0; i < theShowDetails.size(); i++) {
            try {
                IBaseResource resource = theShowDetails.getResource(i);
                String patientId = subjectPatientId(resource);
                if (patientId != null && isDenied(patientId, theRequestDetails)) {
                    theShowDetails.setResource(i, null);
                    ourLog.info("medagent-consent: masked {} (subject Patient/{} has active deny-consent)",
                            resource.fhirType(), patientId);
                }
            } catch (RuntimeException e) {
                ourLog.error("medagent-consent: evaluation error — passing (authz already gated)", e);
            }
        }
    }

    /** True if this patient has an active Consent whose root provision denies sharing. */
    boolean isDenied(String thePatientId, RequestDetails theRequestDetails) {
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
                            && isRecordSharingConsent(c)) {
                        // A withdrawal of RECORD sharing — not a biometric/face-recognition
                        // consent (which governs kiosk check-in, not FHIR visibility).
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

    private static String env(String key, String def) {
        String v = System.getenv(key);
        return v == null ? def : v;
    }
}
