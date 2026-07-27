package lk.medagent.fhir;

import ca.uhn.fhir.rest.api.RestOperationTypeEnum;
import ca.uhn.fhir.rest.api.server.RequestDetails;
import ca.uhn.fhir.rest.server.exceptions.ForbiddenOperationException;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link AuthzInterceptor} (03 §5.1) — the S1 skeleton contract
 * AND the S2 enforce-mode boundary controls (service-credential trust, role/scope
 * gating, no-trawl search shaping, fail-closed).
 */
class AuthzInterceptorTest {

    private static final String KEY = "svc-secret";

    private static RequestDetails req(String serviceKey, String roles, String type, Map<String, String[]> params) {
        RequestDetails rd = mock(RequestDetails.class);
        when(rd.getHeader(AuthzInterceptor.SERVICE_KEY_HEADER)).thenReturn(serviceKey);
        when(rd.getHeader(AuthzInterceptor.ROLES_HEADER)).thenReturn(roles);
        when(rd.getResourceName()).thenReturn(type);
        when(rd.getParameters()).thenReturn(params);
        when(rd.getUserData()).thenReturn(new HashMap<>());
        return rd;
    }

    private static AuthzInterceptor enforcing() {
        return new AuthzInterceptor(AuthzInterceptor.Mode.ENFORCE, false, KEY);
    }

    // --- Skeleton mode (S1 contract, unchanged) ---
    @Test
    void skeleton_writesAlwaysDenied_evenWithPermissiveReadFlag() {
        AuthzInterceptor interceptor = new AuthzInterceptor(true);
        assertThrows(ForbiddenOperationException.class,
                () -> interceptor.authorizeRequest(null, RestOperationTypeEnum.CREATE));
        assertThrows(ForbiddenOperationException.class,
                () -> interceptor.authorizeRequest(null, RestOperationTypeEnum.DELETE));
    }

    @Test
    void skeleton_readsDeniedByDefault_failClosed() {
        AuthzInterceptor interceptor = new AuthzInterceptor(false);
        assertThrows(ForbiddenOperationException.class,
                () -> interceptor.authorizeRequest(null, RestOperationTypeEnum.READ));
    }

    @Test
    void skeleton_readsPassOnlyUnderPermissiveBootstrapFlag() {
        AuthzInterceptor interceptor = new AuthzInterceptor(true);
        interceptor.authorizeRequest(null, RestOperationTypeEnum.READ);
    }

    @Test
    void writeShapedOperationsAreClassifiedAsWrites() {
        assertTrue(AuthzInterceptor.isWrite(RestOperationTypeEnum.CREATE));
        assertTrue(AuthzInterceptor.isWrite(RestOperationTypeEnum.TRANSACTION));
        assertFalse(AuthzInterceptor.isWrite(RestOperationTypeEnum.READ));
        assertFalse(AuthzInterceptor.isWrite(RestOperationTypeEnum.SEARCH_TYPE));
    }

    // --- Enforce mode: trusted-service credential ---
    @Test
    void enforce_deniesWhenServiceCredentialMissing() {
        RequestDetails rd = req(null, "doctor", "Observation", Map.of("patient", new String[]{"1"}));
        assertThrows(ForbiddenOperationException.class,
                () -> enforcing().authorizeRequest(rd, RestOperationTypeEnum.READ));
    }

    @Test
    void enforce_deniesWhenServiceCredentialWrong() {
        RequestDetails rd = req("wrong", "doctor", "Observation", Map.of("patient", new String[]{"1"}));
        assertThrows(ForbiddenOperationException.class,
                () -> enforcing().authorizeRequest(rd, RestOperationTypeEnum.READ));
    }

    @Test
    void enforce_failsClosedWhenNoServiceKeyConfigured() {
        // ENFORCE with an empty configured key must deny everything (never fail open).
        AuthzInterceptor noKey = new AuthzInterceptor(AuthzInterceptor.Mode.ENFORCE, false, "");
        RequestDetails rd = req("anything", "doctor", "Observation", Map.of("patient", new String[]{"1"}));
        assertThrows(ForbiddenOperationException.class,
                () -> noKey.authorizeRequest(rd, RestOperationTypeEnum.READ));
    }

    // --- Enforce mode: role/scope gating (02 §3) ---
    @Test
    void enforce_receptionistMayNotWriteClinicalTypes() {
        RequestDetails rd = req(KEY, "receptionist", "Observation", Map.of());
        assertThrows(ForbiddenOperationException.class,
                () -> enforcing().authorizeRequest(rd, RestOperationTypeEnum.CREATE));
    }

    @Test
    void enforce_doctorMayWriteClinicalTypes() {
        RequestDetails rd = req(KEY, "doctor", "Observation", Map.of());
        assertDoesNotThrow(() -> enforcing().authorizeRequest(rd, RestOperationTypeEnum.CREATE));
    }

    // --- Enforce mode: search shaping (no trawling, 03 §5.1) ---
    @Test
    void enforce_staffSearchWithoutPatientParameterIsRejectedForClinicalTypes() {
        RequestDetails rd = req(KEY, "doctor", "Observation", Map.of());
        assertThrows(ForbiddenOperationException.class,
                () -> enforcing().authorizeRequest(rd, RestOperationTypeEnum.SEARCH_TYPE));
    }

    @Test
    void enforce_patientScopedClinicalSearchIsAllowed() {
        RequestDetails rd = req(KEY, "doctor", "Observation", Map.of("patient", new String[]{"123"}));
        assertDoesNotThrow(() -> enforcing().authorizeRequest(rd, RestOperationTypeEnum.SEARCH_TYPE));
    }

    @Test
    void enforce_nonClinicalSearchWithoutPatientIsAllowed() {
        // e.g. Patient demographic search is not a clinical-compartment trawl.
        RequestDetails rd = req(KEY, "receptionist", "Patient", Map.of("name", new String[]{"perera"}));
        assertDoesNotThrow(() -> enforcing().authorizeRequest(rd, RestOperationTypeEnum.SEARCH_TYPE));
    }

    @Test
    void enforce_workflowFacilitySearchWithoutPatientIsAllowed() {
        // Referral inbox / surveillance line-list: Task & Flag by _tag are legitimate
        // facility-scoped worklists, not patient-compartment trawls.
        RequestDetails task = req(KEY, "doctor", "Task", Map.of("_tag", new String[]{"fac|teaching-hospital"}));
        assertDoesNotThrow(() -> enforcing().authorizeRequest(task, RestOperationTypeEnum.SEARCH_TYPE));
        RequestDetails flag = req(KEY, "doctor", "Flag", Map.of("_tag", new String[]{"disease|dengue"}));
        assertDoesNotThrow(() -> enforcing().authorizeRequest(flag, RestOperationTypeEnum.SEARCH_TYPE));
    }

    // --- Enforce mode: purpose-of-use stamping ---
    @Test
    void enforce_stampsPurposeOfUse() {
        Map<Object, Object> ctx = new HashMap<>();
        RequestDetails rd = mock(RequestDetails.class);
        when(rd.getHeader(AuthzInterceptor.SERVICE_KEY_HEADER)).thenReturn(KEY);
        when(rd.getHeader(AuthzInterceptor.ROLES_HEADER)).thenReturn("doctor");
        when(rd.getHeader(AuthzInterceptor.PURPOSE_HEADER)).thenReturn("BTG");
        when(rd.getResourceName()).thenReturn("Observation");
        when(rd.getParameters()).thenReturn(Map.of("patient", new String[]{"1"}));
        when(rd.getUserData()).thenReturn(ctx);
        enforcing().authorizeRequest(rd, RestOperationTypeEnum.READ);
        assertEquals("BTG", ctx.get(AuthzInterceptor.CTX_PURPOSE_OF_USE));
    }
}
