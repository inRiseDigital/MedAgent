package lk.medagent.fhir;

import ca.uhn.fhir.interceptor.api.Hook;
import ca.uhn.fhir.interceptor.api.Interceptor;
import ca.uhn.fhir.interceptor.api.Pointcut;
import ca.uhn.fhir.rest.api.server.IPreResourceShowDetails;
import ca.uhn.fhir.rest.api.server.RequestDetails;
import ca.uhn.fhir.rest.api.server.storage.TransactionDetails;
import org.hl7.fhir.instance.model.api.IBaseResource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Consent interceptor — second stage of the MedAgent pipeline
 * (docs/solution/03 §2, §5.2; spec §4.3 "consent manager enforces at runtime").
 *
 * <p>Target design: runtime evaluation of the patient's active FHIR {@code Consent}
 * resources — fetch active Consent for the subject, apply {@code provision} rules
 * (actor class, purpose, period, category), verdict. Phase A categories:
 * face-recognition, record-sharing scope (FR-5.2), reminder channels (FR-15.3).
 *
 * <p><b>Caching (03 §5.2 / ADR F-4):</b> verdicts in Redis under
 * {@code consent:{patient}:{purpose}:{actorClass}}, TTL 60 s. Invalidation is
 * event-driven: any write to a {@code Consent} resource publishes
 * {@code authz.invalidate} (shared channel with 02 §7.4) deleting the patient's
 * consent keys — a portal consent flip takes effect within one round-trip.
 *
 * <p><b>Precedence (03 §5.2):</b> deny-by-consent is overridden only by an active
 * break-glass grant with {@code purposeOfUse=BTG} (treatment purpose only); the
 * override is flagged in audit and visible in the patient's access log. Consent
 * can never block the patient's own access, the emergency-profile minimal view
 * (FR-5.7), or legally mandated disclosures.
 *
 * <p><b>S1 status:</b> skeleton. Hooks are wired and observable, but evaluation is
 * a no-op pass-through (authz already fails closed in S1, so nothing sensitive can
 * reach these hooks). TODO(S2/S3): migrate the evaluation onto HAPI's
 * {@code IConsentService} ({@code startOperation} / {@code canSeeResource} /
 * {@code willSeeResource}) as specified in 03 §5.2, backed by the Redis verdict cache.
 */
@Interceptor
public class ConsentInterceptor {

    private static final Logger ourLog = LoggerFactory.getLogger(ConsentInterceptor.class);

    /** Redis key shape per 03 §5.2 — kept here so cache producers/consumers share one constant. */
    static final String CACHE_KEY_TEMPLATE = "consent:%s:%s:%s"; // patient, purpose, actorClass

    /**
     * Filter search/read results against the subject's active Consent provisions.
     *
     * <p>TODO(S2): for each resource — resolve subject patient, resolve requester
     * actor class + purposeOfUse from the request context (stamped by
     * {@link AuthzInterceptor}), consult Redis verdict cache, evaluate Consent
     * provisions on miss, and mask ({@code IPreResourceShowDetails#markResourceAtIndexAsSubset}
     * / remove) anything denied. Fail closed on evaluation error.
     */
    @Hook(Pointcut.STORAGE_PRESHOW_RESOURCES)
    public void applyConsentToShownResources(IPreResourceShowDetails theShowDetails, RequestDetails theRequestDetails) {
        // S1: no-op pass-through (see class javadoc).
        ourLog.trace("medagent-consent: STORAGE_PRESHOW_RESOURCES skeleton invoked");
    }

    /**
     * Consent-cache invalidation trigger: any create of a {@code Consent} resource
     * publishes {@code authz.invalidate} for the subject (03 §5.2).
     *
     * <p>TODO(S2): publish to Redis {@code authz.invalidate}; delete
     * {@code consent:{patient}:*} keys.
     */
    @Hook(Pointcut.STORAGE_PRECOMMIT_RESOURCE_CREATED)
    public void onConsentCreated(IBaseResource theResource, RequestDetails theRequestDetails,
                                 TransactionDetails theTransactionDetails) {
        if (isConsent(theResource)) {
            ourLog.debug("medagent-consent: Consent created — S1 skeleton, invalidation publish TODO");
        }
    }

    /**
     * Consent-cache invalidation trigger on update (03 §5.2).
     *
     * <p>TODO(S2): as {@link #onConsentCreated}.
     */
    @Hook(Pointcut.STORAGE_PRECOMMIT_RESOURCE_UPDATED)
    public void onConsentUpdated(IBaseResource theOldResource, IBaseResource theNewResource,
                                 RequestDetails theRequestDetails, TransactionDetails theTransactionDetails) {
        if (isConsent(theNewResource)) {
            ourLog.debug("medagent-consent: Consent updated — S1 skeleton, invalidation publish TODO");
        }
    }

    static boolean isConsent(IBaseResource theResource) {
        return theResource != null && "Consent".equals(theResource.fhirType());
    }
}
