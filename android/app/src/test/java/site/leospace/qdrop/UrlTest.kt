package site.leospace.qdrop
import org.junit.Test
import org.junit.Assert.*
class UrlTest {
    @Test fun rejectsCredentialsAndUnsafeOrigins() {
        for (u in listOf("https://token@example.com", "https://example.com/path", "http://example.com", "https://example.com?token=a")) assertTrue(runCatching{Credentials.validate(u)}.isFailure)
        Credentials.validate("https://example.com")
    }
    @Test fun privateLanHttpIsAllowedButPublicHttpIsRejected() {
        Credentials.validate("http://192.168.1.8:8000")
        Credentials.validate("http://10.0.0.2:8000")
        Credentials.validate("http://100.64.172.48:8000")
        assertTrue(runCatching{Credentials.validate("http://example.com")}.isFailure)
        assertTrue(runCatching{Credentials.validate("http://8.8.8.8")}.isFailure)
    }
}
