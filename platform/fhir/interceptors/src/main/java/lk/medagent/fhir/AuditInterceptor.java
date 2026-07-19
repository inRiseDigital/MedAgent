package lk.medagent.fhir;

import ca.uhn.fhir.interceptor.api.Hook;
import ca.uhn.fhir.interceptor.api.Interceptor;
import ca.uhn.fhir.interceptor.api.Pointcut;
import ca.uhn.fhir.rest.api.server.RequestDetails;
import ca.uhn.fhir.rest.api.server.storage.TransactionDetails;
import org.hl7.fhir.instance.model.api.IBaseResource;
import org.hl7.fhir.r4.model.AuditEvent;
import org.hl7.fhir.r4.model.Coding;
import org.hl7.fhir.r4.model.InstantType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Date;

/**
 * Audit interceptor — final stage of the MedAgent pipeline
 * (docs/solution/03 §2, §5.3, §5.4; NFR-8 100% coverage, tamper-evident).
 *
 * <p>Every storage event becomes a FHIR {@code AuditEvent}: actor (Keycloak
 * {@code sub} → Practitioner/Patient ref + grant type from request context),
 * action (C/R/U/D/E), entities (resource refs; for searches, the query string +
 * returned ids), facility, {@code purposeOfUse} (TREAT default / BTG / PATRQT),
 * outcome. Writes hook {@code STORAGE_PRECOMMIT_RESOURCE_*} so the write and its
 * audit commit atomically or not at all (03 §5.3). This is the single choke
 * point — there is no storage path around the interceptor.
 *
 * <p><b>Tamper evidence (03 §5.4, detail in 08):</b> AuditEvents land in the
 * dedicated append-only {@code audit} partition (monthly range partitions, the
 * HAPI DB role has INSERT+SELECT only). Each event carries two extensions:
 * {@code audit-seq} (per-partition monotonic sequence) and {@code audit-prev-hash}
 * (SHA-256 over the canonical JSON of the previous event ⊕ its hash). S1 writes
 * the extension URLs with placeholder values; the chain computation, genesis
 * derivation and nightly verification job land per the sprint plan.
 *
 * <p><b>S1 status:</b> real skeleton — builds a well-formed {@code AuditEvent}
 * with hash-chain placeholder extensions for every precommit write hook and logs
 * it. TODO(S2): persist into the audit partition inside the same transaction;
 * add read/search auditing via {@code STORAGE_PRESHOW_RESOURCES} +
 * {@code SERVER_OUTGOING_RESPONSE} and denial auditing from the authz/consent
 * denial hooks (denials are audited too — FR-6.3).
 */
@Interceptor
public class AuditInterceptor {

    private static final Logger ourLog = LoggerFactory.getLogger(AuditInterceptor.class);

    /** Extension URLs per 03 §5.4 / 08 (canonical base fixed in 03 §3). */
    public static final String EXT_AUDIT_SEQ = "https://fhir.medagent.health.lk/StructureDefinition/audit-seq";
    public static final String EXT_AUDIT_PREV_HASH = "https://fhir.medagent.health.lk/StructureDefinition/audit-prev-hash";

    /** S1 placeholder until the chain writer lands — makes unwired chains grep-able, never mistakable for a real hash. */
    static final String HASH_CHAIN_PLACEHOLDER = "S1-UNCHAINED";

    @Hook(Pointcut.STORAGE_PRECOMMIT_RESOURCE_CREATED)
    public void auditCreated(IBaseResource theResource, RequestDetails theRequestDetails,
                             TransactionDetails theTransactionDetails) {
        emit(buildAuditEvent(AuditEvent.AuditEventAction.C, theResource, theRequestDetails));
    }

    @Hook(Pointcut.STORAGE_PRECOMMIT_RESOURCE_UPDATED)
    public void auditUpdated(IBaseResource theOldResource, IBaseResource theNewResource,
                             RequestDetails theRequestDetails, TransactionDetails theTransactionDetails) {
        emit(buildAuditEvent(AuditEvent.AuditEventAction.U, theNewResource, theRequestDetails));
    }

    @Hook(Pointcut.STORAGE_PRECOMMIT_RESOURCE_DELETED)
    public void auditDeleted(IBaseResource theResource, RequestDetails theRequestDetails,
                             TransactionDetails theTransactionDetails) {
        // Deletes are refused for clinical types by the authz layer (03 §1); the sole
        // surviving path is the §8.2 DSR erasure flow — which must still audit.
        emit(buildAuditEvent(AuditEvent.AuditEventAction.D, theResource, theRequestDetails));
    }

    /**
     * Build a well-formed AuditEvent per 03 §5.3.
     *
     * <p>TODO(S2): populate agent from Keycloak {@code sub} + grant type
     * (request context stamped by {@link AuthzInterceptor}), facility, and
     * purposeOfUse (TREAT/BTG/PATRQT) from {@link AuthzInterceptor#CTX_PURPOSE_OF_USE}.
     */
    AuditEvent buildAuditEvent(AuditEvent.AuditEventAction theAction, IBaseResource theResource,
                               RequestDetails theRequestDetails) {
        AuditEvent auditEvent = new AuditEvent();
        auditEvent.setAction(theAction);
        auditEvent.setRecordedElement(new InstantType(new Date()));
        auditEvent.setType(new Coding("http://terminology.hl7.org/CodeSystem/audit-event-type",
                "rest", "RESTful Operation"));
        auditEvent.setOutcome(AuditEvent.AuditEventOutcome._0); // success; denial paths audit from their own hooks (TODO S2)

        AuditEvent.AuditEventEntityComponent entity = auditEvent.addEntity();
        if (theResource != null && theResource.getIdElement() != null) {
            entity.getWhat().setReference(theResource.getIdElement().toUnqualifiedVersionless().getValue());
        }

        AuditEvent.AuditEventAgentComponent agent = auditEvent.addAgent();
        agent.setRequestor(true);
        // TODO(S2): agent.who = Practitioner/Patient reference resolved from token sub;
        //           agent purposeOfUse from request context (TREAT default, BTG, PATRQT).

        // Hash-chain placeholders (03 §5.4) — real values are assigned by the chain
        // writer at persist time: seq = per-partition monotonic counter,
        // prev-hash = SHA-256(canonical JSON of previous event ⊕ its hash).
        auditEvent.addExtension(EXT_AUDIT_SEQ, new org.hl7.fhir.r4.model.DecimalType(-1));
        auditEvent.addExtension(EXT_AUDIT_PREV_HASH, new org.hl7.fhir.r4.model.StringType(HASH_CHAIN_PLACEHOLDER));

        return auditEvent;
    }

    /**
     * TODO(S2): persist into the append-only {@code audit} partition within the
     * caller's transaction (STORAGE_PRECOMMIT_* runs inside it — atomicity per
     * 03 §5.3). S1 logs the event so the pipeline is observable end-to-end.
     */
    private void emit(AuditEvent theAuditEvent) {
        ourLog.info("medagent-audit: AuditEvent action={} entity={} (S1 skeleton — persistence TODO)",
                theAuditEvent.getAction(),
                theAuditEvent.hasEntity() ? theAuditEvent.getEntityFirstRep().getWhat().getReference() : "n/a");
    }
}
