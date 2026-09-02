package lk.medagent.fhir;

import org.hl7.fhir.r4.model.AuditEvent;
import org.hl7.fhir.r4.model.Observation;
import org.hl7.fhir.r4.model.StringType;
import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Unit tests for {@link AuditInterceptor} (03 §5.3, §5.4).
 *
 * <p>Covers the AuditEvent shape, the enriched actor/purpose, and the real
 * per-process hash chain. Transactional persistence into a dedicated append-only
 * partition and a DB-continued chain across restarts remain integration-level (S3+).
 */
class AuditInterceptorTest {

    // No FHIR base configured → log-only, no network — safe for unit tests.
    private final AuditInterceptor myInterceptor = new AuditInterceptor("", "");

    @Test
    void buildsWellFormedAuditEventForCreate() {
        Observation resource = new Observation();
        resource.setId("Observation/123/_history/1");

        AuditEvent event = myInterceptor.buildAuditEvent(AuditEvent.AuditEventAction.C, resource, null);

        assertEquals(AuditEvent.AuditEventAction.C, event.getAction());
        assertNotNull(event.getRecorded());
        assertEquals("Observation/123", event.getEntityFirstRep().getWhat().getIdentifier().getValue());
        assertNotNull(event.getSource().getObserver().getDisplay());
        assertTrue(event.getAgentFirstRep().getRequestor());
    }

    @Test
    void chainAssignsMonotonicSeqAndAdvancingPrevHash() {
        AuditEvent first = myInterceptor.buildAuditEvent(AuditEvent.AuditEventAction.C, new Observation(), null);
        myInterceptor.chain(first);
        AuditEvent second = myInterceptor.buildAuditEvent(AuditEvent.AuditEventAction.U, new Observation(), null);
        myInterceptor.chain(second);

        assertNotNull(first.getExtensionByUrl(AuditInterceptor.EXT_AUDIT_SEQ), "audit-seq must be present (03 §5.4)");
        assertNotNull(first.getExtensionByUrl(AuditInterceptor.EXT_AUDIT_PREV_HASH), "audit-prev-hash must be present");

        // Monotonic sequence.
        assertEquals("1", first.getExtensionByUrl(AuditInterceptor.EXT_AUDIT_SEQ).getValue().primitiveValue());
        assertEquals("2", second.getExtensionByUrl(AuditInterceptor.EXT_AUDIT_SEQ).getValue().primitiveValue());

        // First event's prev-hash is the genesis head; the second's is the chained hash of the first (advanced).
        String firstPrev = ((StringType) first.getExtensionByUrl(AuditInterceptor.EXT_AUDIT_PREV_HASH).getValue()).getValue();
        String secondPrev = ((StringType) second.getExtensionByUrl(AuditInterceptor.EXT_AUDIT_PREV_HASH).getValue()).getValue();
        assertEquals(AuditInterceptor.GENESIS_HASH, firstPrev, "first event chains from genesis");
        assertNotEquals(AuditInterceptor.GENESIS_HASH, secondPrev, "chain must advance after the first event");
        assertEquals(64, secondPrev.length(), "prev-hash is a SHA-256 hex digest");
    }

    @Test
    void enrichesActorRoleAndPurposeFromRequestContext() {
        // A RequestDetails carrying the forwarded roles + the Authz-stamped purpose.
        var rd = org.mockito.Mockito.mock(ca.uhn.fhir.rest.api.server.RequestDetails.class);
        org.mockito.Mockito.when(rd.getHeader(AuditInterceptor.ROLES_HEADER)).thenReturn("doctor,system");
        java.util.Map<Object, Object> userData = new java.util.HashMap<>();
        userData.put(AuthzInterceptor.CTX_PURPOSE_OF_USE, "TREAT");
        org.mockito.Mockito.when(rd.getUserData()).thenReturn(userData);

        AuditEvent event = myInterceptor.buildAuditEvent(AuditEvent.AuditEventAction.C, new Observation(), rd);

        assertEquals("doctor,system", event.getAgentFirstRep().getAltId());
        assertEquals("TREAT", event.getAgentFirstRep().getPurposeOfUseFirstRep().getCodingFirstRep().getCode());
    }

    @Test
    @Disabled("S3: persistence into a dedicated append-only partition + DB-continued chain across restarts (03 §5.3-5.4)")
    void auditPersistsToAppendOnlyPartitionAndContinuesChain() {
        // TODO(S3): integration-level.
    }

    @Test
    @Disabled("S2: reads/searches audited via STORAGE_PRESHOW_RESOURCES + SERVER_OUTGOING_RESPONSE incl. query string + result ids")
    void readsAndSearchesAreAudited() {
        // TODO(S2)
    }
}
