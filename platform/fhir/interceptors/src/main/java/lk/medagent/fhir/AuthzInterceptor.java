package lk.medagent.fhir;

import ca.uhn.fhir.interceptor.api.Hook;
import ca.uhn.fhir.interceptor.api.Interceptor;
import ca.uhn.fhir.interceptor.api.Pointcut;
import ca.uhn.fhir.rest.api.RestOperationTypeEnum;
import ca.uhn.fhir.rest.api.server.RequestDetails;
import ca.uhn.fhir.rest.server.exceptions.ForbiddenOperationException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Authorisation interceptor — first stage of the MedAgent pipeline
 * (docs/solution/03 §2, §5.1; care-relationship model in 02 §7).
 *
 * <p>Responsibilities (target design):
 * <ol>
 *   <li>Token / scope / audience re-verification — defence in depth behind the
 *       gateway (audience {@code fhir-gateway}, 02 §2).</li>
 *   <li>Role/scope table (02 §3): gate resource types and interactions per role
 *       (e.g. receptionist never touches clinical types; nurse writes limited to
 *       vital-sign Observations).</li>
 *   <li>Care-relationship check: for each patient the request touches, consult
 *       the shared Redis decision cache ({@code authz:{actor}:{patient}}, TTL 60s)
 *       and fall back to core-api {@code GET /internal/authz/decision} (02 §7.2,
 *       ADR F-4). Break-glass grants arrive through the same decision call and
 *       stamp the request context {@code purposeOfUse=BTG}.</li>
 *   <li>Patient/guardian context ({@code patient.self} scope): confine to the
 *       subject's (or ward's) patient compartment.</li>
 *   <li>Search shaping: staff searches without a patient parameter are rejected
 *       for clinical resource types (no trawling, 03 §5.1).</li>
 * </ol>
 *
 * <p><b>S1 status:</b> skeleton. Fail-closed for ALL writes/deletes; reads are
 * denied unless the {@code MEDAGENT_AUTHZ_PERMISSIVE_READ} bootstrap flag is
 * set (dev-only, never staging/pilot — see application.yaml). The invariant
 * asserted by integration tests from S2 on: core-api unreachable =&gt; staff
 * clinical reads DENY, never allow (03 §5).
 */
@Interceptor
public class AuthzInterceptor {

    private static final Logger ourLog = LoggerFactory.getLogger(AuthzInterceptor.class);

    /** Dev bootstrap flag only — see application.yaml `medagent.authz.permissive-read`. */
    static final String PERMISSIVE_READ_ENV = "MEDAGENT_AUTHZ_PERMISSIVE_READ";

    /** Request-context key set to "BTG" when a break-glass grant backs the access (02 §6). */
    public static final String CTX_PURPOSE_OF_USE = "medagent.purposeOfUse";

    private final boolean myPermissiveRead;

    public AuthzInterceptor() {
        this(Boolean.parseBoolean(System.getenv().getOrDefault(PERMISSIVE_READ_ENV, "false")));
    }

    AuthzInterceptor(boolean thePermissiveRead) {
        myPermissiveRead = thePermissiveRead;
        if (myPermissiveRead) {
            ourLog.warn("AuthzInterceptor running with PERMISSIVE READ bootstrap flag — dev only, never staging/pilot");
        }
    }

    /**
     * Entry-point authorisation check, before the request is handed to its handler.
     *
     * <p>TODO(S2): full implementation per 03 §5.1 —
     * <ul>
     *   <li>re-verify JWT scope + audience claims from the request context;</li>
     *   <li>role/scope table lookup (02 §3);</li>
     *   <li>Redis decision-cache GET, core-api decision fallback, fail-closed on error;</li>
     *   <li>stamp {@link #CTX_PURPOSE_OF_USE} (TREAT default / BTG / PATRQT);</li>
     *   <li>reject clinical-type searches lacking a patient parameter;</li>
     *   <li>add STORAGE_PREACCESS_RESOURCES / STORAGE_PRESHOW_RESOURCES hooks for
     *       per-resource checks on search results (03 §5.1) and compartment
     *       enforcement via HAPI's authorization rule builder.</li>
     * </ul>
     */
    @Hook(Pointcut.SERVER_INCOMING_REQUEST_PRE_HANDLED)
    public void authorizeRequest(RequestDetails theRequestDetails, RestOperationTypeEnum theOperation) {
        if (theOperation == null) {
            return;
        }
        if (isWrite(theOperation)) {
            // S1: FAIL CLOSED. No write reaches storage until the decision path exists.
            // TODO(S2): permit writes carrying a valid permit decision (02 §7.2).
            throw new ForbiddenOperationException(
                    "medagent-authz: write operations are denied (S1 fail-closed skeleton; decision service not yet wired)");
        }
        if (!myPermissiveRead) {
            // S1: reads fail closed too, unless the dev bootstrap flag is set.
            // TODO(S2): replace with role/scope + care-relationship decision (03 §5.1).
            throw new ForbiddenOperationException(
                    "medagent-authz: read denied (S1 fail-closed skeleton; set " + PERMISSIVE_READ_ENV
                            + "=true for local bootstrapping only)");
        }
        ourLog.debug("medagent-authz: permissive-read bootstrap allowed {} {}",
                theOperation, theRequestDetails != null ? theRequestDetails.getRequestPath() : "?");
    }

    /** Write/delete-shaped interactions that must always fail closed in S1 (03 §1: deletes are interceptor-refused). */
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
