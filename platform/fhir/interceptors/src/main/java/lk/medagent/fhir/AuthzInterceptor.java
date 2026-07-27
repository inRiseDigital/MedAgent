package lk.medagent.fhir;

import ca.uhn.fhir.interceptor.api.Hook;
import ca.uhn.fhir.interceptor.api.Interceptor;
import ca.uhn.fhir.interceptor.api.Pointcut;
import ca.uhn.fhir.rest.api.RestOperationTypeEnum;
import ca.uhn.fhir.rest.api.server.RequestDetails;
import ca.uhn.fhir.rest.server.exceptions.ForbiddenOperationException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * Authorisation interceptor — first stage of the MedAgent pipeline
 * (docs/solution/03 §2, §5.1; care-relationship model in 02 §7).
 *
 * <p>Two modes, selected by {@code MEDAGENT_AUTHZ_MODE}:
 * <ul>
 *   <li><b>skeleton</b> (default): the S1 fail-closed contract — writes always
 *       denied, reads denied unless the dev {@code MEDAGENT_AUTHZ_PERMISSIVE_READ}
 *       flag is set. Keeps the historical bootstrap behaviour and the running dev
 *       stack (which does not enable this mode) untouched.</li>
 *   <li><b>enforce</b>: real boundary controls (03 §5.1) —
 *     <ol>
 *       <li><b>Trusted-service credential</b> — every request must carry the shared
 *           {@code X-MedAgent-Service-Key} (set from {@code MEDAGENT_SERVICE_KEY}).
 *           HAPI has no published ports; this closes the "network breach reaches
 *           HAPI directly" and "a service without the credential" paths.</li>
 *       <li><b>Role/scope gate</b> — only clinical-writer roles (doctor/nurse/admin/
 *           system, forwarded in {@code X-MedAgent-Roles}) may write clinical
 *           resource types; a receptionist can never write clinical data (02 §3).</li>
 *       <li><b>Search shaping</b> — a search of a clinical type without a patient
 *           parameter is rejected (no trawling, 03 §5.1).</li>
 *       <li><b>purposeOfUse</b> stamp (TREAT default / BTG break-glass).</li>
 *     </ol>
 *     Any evaluation error fails closed (deny).</li>
 * </ul>
 *
 * <p><b>Staged rollout (R-1):</b> per-user care-relationship enforcement via the
 * Redis decision cache + core-api {@code GET /internal/authz/decision} is the
 * remaining S2 step (documented in the module README); enforce-mode today is the
 * service-trust + role + no-trawl boundary, activated only once core-api forwards
 * the service key + roles on its FHIR calls.
 */
@Interceptor
public class AuthzInterceptor {

    private static final Logger ourLog = LoggerFactory.getLogger(AuthzInterceptor.class);

    public enum Mode { SKELETON, ENFORCE }

    static final String MODE_ENV = "MEDAGENT_AUTHZ_MODE";                 // skeleton | enforce
    static final String PERMISSIVE_READ_ENV = "MEDAGENT_AUTHZ_PERMISSIVE_READ";
    static final String SERVICE_KEY_ENV = "MEDAGENT_SERVICE_KEY";
    static final String SERVICE_KEY_HEADER = "X-MedAgent-Service-Key";
    static final String ROLES_HEADER = "X-MedAgent-Roles";               // csv, forwarded by core-api
    static final String PURPOSE_HEADER = "X-MedAgent-Purpose";           // TREAT | BTG | PATRQT

    /** Request-context key set to the purpose of use backing the access (02 §6). */
    public static final String CTX_PURPOSE_OF_USE = "medagent.purposeOfUse";

    /** Clinical resource types a receptionist may never write (write role-gate). */
    static final Set<String> CLINICAL_TYPES = Set.of(
            "Observation", "Condition", "MedicationRequest", "DiagnosticReport", "DocumentReference",
            "AllergyIntolerance", "Immunization", "ServiceRequest", "Encounter", "Specimen", "Flag",
            "Consent", "RelatedPerson", "ImagingStudy", "Task", "Procedure");

    /** Patient-compartment record types that must never be searched without a
     *  patient scope (no-trawl, 03 §5.1). Deliberately EXCLUDES workflow types
     *  (Task/ServiceRequest/Flag/Appointment) whose facility-scoped `_tag` searches
     *  are legitimate cross-patient worklists (referrals inbox, surveillance). */
    static final Set<String> COMPARTMENT_TYPES = Set.of(
            "Observation", "Condition", "MedicationRequest", "DiagnosticReport", "DocumentReference",
            "AllergyIntolerance", "Immunization", "Encounter", "Specimen", "ImagingStudy", "Procedure");

    /** Roles permitted to write clinical resource types (02 §3). */
    static final Set<String> CLINICAL_WRITERS = Set.of("doctor", "nurse", "admin", "system");

    /** Search parameters that scope a query to a patient (satisfy the no-trawl rule). */
    static final Set<String> PATIENT_SCOPE_PARAMS = Set.of("patient", "subject", "_id");

    private final Mode myMode;
    private final boolean myPermissiveRead;
    private final String myServiceKey;

    public AuthzInterceptor() {
        this(parseMode(env(MODE_ENV, "skeleton")),
                Boolean.parseBoolean(env(PERMISSIVE_READ_ENV, "false")),
                env(SERVICE_KEY_ENV, ""));
    }

    /** Skeleton-mode constructor (backward-compatible with the S1 tests). */
    AuthzInterceptor(boolean thePermissiveRead) {
        this(Mode.SKELETON, thePermissiveRead, "");
    }

    AuthzInterceptor(Mode theMode, boolean thePermissiveRead, String theServiceKey) {
        myMode = theMode;
        myPermissiveRead = thePermissiveRead;
        myServiceKey = theServiceKey == null ? "" : theServiceKey;
        if (myMode == Mode.ENFORCE) {
            ourLog.info("AuthzInterceptor: ENFORCE mode (service-credential + role/scope + no-trawl)");
            if (myServiceKey.isEmpty()) {
                ourLog.warn("AuthzInterceptor ENFORCE with no {} configured — all requests will be denied", SERVICE_KEY_ENV);
            }
        } else if (myPermissiveRead) {
            ourLog.warn("AuthzInterceptor SKELETON with PERMISSIVE READ — dev only, never staging/pilot");
        }
    }

    @Hook(Pointcut.SERVER_INCOMING_REQUEST_PRE_HANDLED)
    public void authorizeRequest(RequestDetails theRequestDetails, RestOperationTypeEnum theOperation) {
        if (theOperation == null) {
            return;
        }
        if (myMode == Mode.ENFORCE) {
            enforce(theRequestDetails, theOperation);
            return;
        }
        // SKELETON (S1): fail closed. Writes always denied; reads only under the flag.
        if (isWrite(theOperation)) {
            throw new ForbiddenOperationException(
                    "medagent-authz: write operations are denied (S1 fail-closed skeleton; enable enforce mode)");
        }
        if (!myPermissiveRead) {
            throw new ForbiddenOperationException(
                    "medagent-authz: read denied (S1 fail-closed skeleton; set " + PERMISSIVE_READ_ENV
                            + "=true for local bootstrapping only)");
        }
    }

    /** ENFORCE-mode boundary checks. Fails closed on any error (03 §5). */
    void enforce(RequestDetails theRequestDetails, RestOperationTypeEnum theOperation) {
        try {
            if (theRequestDetails == null) {
                throw new ForbiddenOperationException("medagent-authz: no request context");
            }
            // 1. Trusted-service credential — constant-time compare, deny if absent/wrong.
            String presented = theRequestDetails.getHeader(SERVICE_KEY_HEADER);
            if (myServiceKey.isEmpty() || presented == null || !constantTimeEquals(myServiceKey, presented)) {
                throw new ForbiddenOperationException(
                        "medagent-authz: trusted-service credential required");
            }
            Set<String> roles = rolesOf(theRequestDetails);
            String type = theRequestDetails.getResourceName();

            // 2. Role/scope: only clinical writers may write clinical resource types.
            if (isWrite(theOperation) && isClinicalType(type) && Collections.disjoint(roles, CLINICAL_WRITERS)) {
                throw new ForbiddenOperationException(
                        "medagent-authz: role " + roles + " may not write clinical resource " + type);
            }

            // 3. Search shaping: patient-compartment records must be patient-scoped
            //    (no trawling). Workflow types (Task/ServiceRequest/Flag) are exempt —
            //    their facility-scoped worklist searches are legitimate.
            if (theOperation == RestOperationTypeEnum.SEARCH_TYPE && type != null
                    && COMPARTMENT_TYPES.contains(type) && !hasPatientScope(theRequestDetails)) {
                throw new ForbiddenOperationException(
                        "medagent-authz: search of patient-compartment type " + type
                                + " requires a patient parameter");
            }

            // 4. Stamp purpose of use (TREAT default; BTG break-glass carried in a header).
            String purpose = theRequestDetails.getHeader(PURPOSE_HEADER);
            theRequestDetails.getUserData().put(CTX_PURPOSE_OF_USE,
                    ("BTG".equalsIgnoreCase(purpose) || "PATRQT".equalsIgnoreCase(purpose))
                            ? purpose.toUpperCase(Locale.ROOT) : "TREAT");
        } catch (ForbiddenOperationException e) {
            throw e;
        } catch (RuntimeException e) {
            // Fail closed on any unexpected evaluation error.
            ourLog.warn("medagent-authz: evaluation error — failing closed", e);
            throw new ForbiddenOperationException("medagent-authz: authorization evaluation failed (fail-closed)");
        }
    }

    static boolean isClinicalType(String theType) {
        return theType != null && CLINICAL_TYPES.contains(theType);
    }

    static boolean hasPatientScope(RequestDetails theRequestDetails) {
        Map<String, String[]> params = theRequestDetails.getParameters();
        if (params == null) {
            return false;
        }
        for (String p : PATIENT_SCOPE_PARAMS) {
            if (params.containsKey(p) && params.get(p) != null && params.get(p).length > 0) {
                return true;
            }
        }
        return false;
    }

    private static Set<String> rolesOf(RequestDetails theRequestDetails) {
        String header = theRequestDetails.getHeader(ROLES_HEADER);
        Set<String> roles = new HashSet<>();
        if (header != null && !header.isBlank()) {
            for (String r : header.split(",")) {
                String t = r.trim().toLowerCase(Locale.ROOT);
                if (!t.isEmpty()) {
                    roles.add(t);
                }
            }
        }
        return roles;
    }

    private static boolean constantTimeEquals(String a, String b) {
        if (a.length() != b.length()) {
            return false;
        }
        int diff = 0;
        for (int i = 0; i < a.length(); i++) {
            diff |= a.charAt(i) ^ b.charAt(i);
        }
        return diff == 0;
    }

    private static Mode parseMode(String v) {
        return "enforce".equalsIgnoreCase(v) ? Mode.ENFORCE : Mode.SKELETON;
    }

    private static String env(String key, String def) {
        String v = System.getenv(key);
        return v == null ? def : v;
    }

    /** Write/delete-shaped interactions (03 §1: deletes are interceptor-refused). */
    static boolean isWrite(RestOperationTypeEnum theOperation) {
        switch (theOperation) {
            case CREATE:
            case UPDATE:
            case PATCH:
            case DELETE:
            case TRANSACTION:
            case BATCH:
                return true;
            default:
                return false;
        }
    }
}
