package lk.medagent.fhir;

import org.hl7.fhir.r4.model.AuditEvent;
import org.hl7.fhir.r4.model.Observation;
import org.hl7.fhir.r4.model.StringType;
import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Unit tests for {@link AuditInterceptor} (03 §5.3, §5.4).
 *
 * <p>S1 scope: AuditEvent shape + hash-chain placeholder extensions. The chain
 * computation, transactional persistence into the audit partition, read/search
 * auditing and denial auditing are S2+ (with integration tests per 10 §3.4).
 */
class AuditInterceptorTest {

    private final AuditInterceptor myInterceptor = new AuditInterceptor();

    @Test
    void buildsWellFormedAuditEventForCreate() {
        Observation resource = new Observation();
        resource.setId("Observation/123/_history/1");

        AuditEvent event = myInterceptor.buildAuditEvent(AuditEvent.AuditEventAction.C, resource, null);

        assertEquals(AuditEvent.AuditEventAction.C, event.getAction());
        assertNotNull(event.getRecorded());
        assertEquals("Observation/123", event.getEntityFirstRep().getWhat().getReference());
        assertTrue(event.getAgentFirstRep().getRequestor());
    }

    @Test
    void everyAuditEventCarriesHashChainExtensions() {
        AuditEvent event = myInterceptor.buildAuditEvent(AuditEvent.AuditEventAction.U, new Observation(), null);

        assertNotNull(event.getExtensionByUrl(AuditInterceptor.EXT_AUDIT_SEQ),
                "audit-seq extension must be present (03 §5.4)");
        assertNotNull(event.getExtensionByUrl(AuditInterceptor.EXT_AUDIT_PREV_HASH),
                "audit-prev-hash extension must be present (03 §5.4)");
        assertEquals(AuditInterceptor.HASH_CHAIN_PLACEHOLDER,
                ((StringType) event.getExtensionByUrl(AuditInterceptor.EXT_AUDIT_PREV_HASH).getValue()).getValue(),
                "S1 placeholder value until the chain writer lands");
    }

    @Test
    @Disabled("S2: audit persists in the same transaction as the write — atomic commit or neither (03 §5.3)")
    void auditCommitsAtomicallyWithTheWrite() {
        // TODO(S2): integration-level; STORAGE_PRECOMMIT_* runs inside the storage transaction.
    }

    @Test
    @Disabled("S2: reads/searches audited via STORAGE_PRESHOW_RESOURCES + SERVER_OUTGOING_RESPONSE incl. query string + result ids")
    void readsAndSearchesAreAudited() {
        // TODO(S2)
    }

    @Test
    @Disabled("S2: authz/consent denials emit AuditEvent from their own hooks (FR-6.3 security signal)")
    void denialsAreAuditedToo() {
        // TODO(S2)
    }

    @Test
    @Disabled("S3: audit-seq monotonic per partition; audit-prev-hash = SHA-256(prev canonical JSON ⊕ prev hash) (03 §5.4, 08)")
    void hashChainValuesAreComputedAtPersistTime() {
        // TODO(S3)
    }
}
