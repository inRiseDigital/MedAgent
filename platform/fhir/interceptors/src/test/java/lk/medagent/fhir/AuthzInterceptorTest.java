package lk.medagent.fhir;

import ca.uhn.fhir.rest.api.RestOperationTypeEnum;
import ca.uhn.fhir.rest.server.exceptions.ForbiddenOperationException;
import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Unit tests for {@link AuthzInterceptor} (03 §5.1).
 *
 * <p>S1 scope: the fail-closed skeleton contract. The full suite (role/scope
 * matrix per 02 §3, decision-cache behaviour, compartment enforcement,
 * search-shaping, core-api-unreachable => deny) lands with the S2 implementation
 * and the integration tests in the compose `test` profile (10 §3.4).
 */
class AuthzInterceptorTest {

    @Test
    void writesAreAlwaysDenied_evenWithPermissiveReadFlag() {
        AuthzInterceptor interceptor = new AuthzInterceptor(true);
        assertThrows(ForbiddenOperationException.class,
                () -> interceptor.authorizeRequest(null, RestOperationTypeEnum.CREATE));
        assertThrows(ForbiddenOperationException.class,
                () -> interceptor.authorizeRequest(null, RestOperationTypeEnum.DELETE));
    }

    @Test
    void readsAreDeniedByDefault_failClosed() {
        AuthzInterceptor interceptor = new AuthzInterceptor(false);
        assertThrows(ForbiddenOperationException.class,
                () -> interceptor.authorizeRequest(null, RestOperationTypeEnum.READ));
        assertThrows(ForbiddenOperationException.class,
                () -> interceptor.authorizeRequest(null, RestOperationTypeEnum.SEARCH_TYPE));
    }

    @Test
    void readsPassOnlyUnderPermissiveBootstrapFlag() {
        AuthzInterceptor interceptor = new AuthzInterceptor(true);
        // Must not throw — dev bootstrap only (application.yaml medagent.authz.permissive-read).
        interceptor.authorizeRequest(null, RestOperationTypeEnum.READ);
    }

    @Test
    void writeShapedOperationsAreClassifiedAsWrites() {
        assertTrue(AuthzInterceptor.isWrite(RestOperationTypeEnum.CREATE));
        assertTrue(AuthzInterceptor.isWrite(RestOperationTypeEnum.UPDATE));
        assertTrue(AuthzInterceptor.isWrite(RestOperationTypeEnum.PATCH));
        assertTrue(AuthzInterceptor.isWrite(RestOperationTypeEnum.DELETE));
        assertTrue(AuthzInterceptor.isWrite(RestOperationTypeEnum.TRANSACTION));
        assertFalse(AuthzInterceptor.isWrite(RestOperationTypeEnum.READ));
        assertFalse(AuthzInterceptor.isWrite(RestOperationTypeEnum.SEARCH_TYPE));
    }

    @Test
    @Disabled("S2: decision-cache + core-api decision call — deny when core-api unreachable (03 §5 fail-closed invariant)")
    void staffClinicalReadDeniesWhenDecisionServiceUnreachable() {
        // TODO(S2): mock Redis miss + core-api connection failure; assert deny, never allow.
    }

    @Test
    @Disabled("S2: search shaping — staff search without patient parameter rejected for clinical types (03 §5.1)")
    void staffSearchWithoutPatientParameterIsRejectedForClinicalTypes() {
        // TODO(S2)
    }
}
