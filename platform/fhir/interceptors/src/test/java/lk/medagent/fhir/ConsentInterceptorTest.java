package lk.medagent.fhir;

import org.hl7.fhir.r4.model.Consent;
import org.hl7.fhir.r4.model.Observation;
import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Unit tests for {@link ConsentInterceptor} (03 §5.2).
 *
 * <p>S1 scope: skeleton wiring. The behavioural suite (provision evaluation,
 * Redis verdict cache + event-driven invalidation, BTG precedence, patient
 * self-access never blocked) lands with the S2/S3 IConsentService implementation.
 */
class ConsentInterceptorTest {

    @Test
    void consentResourcesAreRecognisedForInvalidationTriggers() {
        assertTrue(ConsentInterceptor.isConsent(new Consent()));
        assertFalse(ConsentInterceptor.isConsent(new Observation()));
        assertFalse(ConsentInterceptor.isConsent(null));
    }

    @Test
    void preshowIsANoOpWhenNoResultsToEvaluate() {
        // Must not throw on a null show-details (no results to evaluate).
        new ConsentInterceptor().applyConsentToShownResources(null, null);
    }

    @Test
    void resolvesTheSubjectPatientForCompartmentTypes() {
        Observation obs = new Observation();
        obs.getSubject().setReference("Patient/456");
        assertEquals("456", ConsentInterceptor.subjectPatientId(obs));

        // A resource with no patient linkage is not consent-scoped here.
        org.hl7.fhir.r4.model.Organization org = new org.hl7.fhir.r4.model.Organization();
        assertNull(ConsentInterceptor.subjectPatientId(org));
        assertNull(ConsentInterceptor.subjectPatientId(null));
    }

    @Test
    void faceRecognitionConsentIsNotARecordSharingWithdrawal() {
        // A biometric (face-recognition) consent uses provision.type=deny to mean
        // "no face check-in" — it must NEVER mask clinical resources.
        Consent face = new Consent();
        face.addCategory().addCoding()
                .setSystem("https://fhir.medagent.health.lk/cs/consent-category").setCode("face-recognition");
        assertFalse(ConsentInterceptor.isRecordSharingConsent(face));

        // A consent without a non-sharing category is treated as a record-sharing scope.
        assertTrue(ConsentInterceptor.isRecordSharingConsent(new Consent()));
    }

    @Test
    @Disabled("S2/S3: live deny-provision evaluation over the store (integration — needs a running server)")
    void activeDenyConsentMasksTheResource() {
        // TODO: integration-level — covered live in the enforce overlay smoke test.
    }

    @Test
    @Disabled("S2: Consent write publishes authz.invalidate and clears consent:{patient}:* keys (03 §5.2)")
    void consentWriteInvalidatesCachedVerdictsEagerly() {
        // TODO(S2)
    }

    @Test
    @Disabled("S2: deny-by-consent overridden only by active BTG grant, treatment purpose only; override flagged in audit")
    void breakGlassOverridesConsentDenyForTreatmentOnly() {
        // TODO(S2)
    }

    @Test
    @Disabled("S2: consent can never block the patient's own access (PATRQT) or the FR-5.7 emergency minimal view")
    void patientSelfAccessIsNeverBlockedByConsent() {
        // TODO(S2)
    }
}
