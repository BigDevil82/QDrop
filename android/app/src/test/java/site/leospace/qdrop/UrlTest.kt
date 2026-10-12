package site.leospace.qdrop
import org.junit.Test
import org.junit.Assert.*
class UrlTest {
    @Test fun rejectsCredentialsAndUnsafeOrigins() {
        for (u in listOf("https://token@example.com", "https://example.com/path", "http://example.com", "https://example.com?token=a")) assertTrue(runCatching{Credentials.validate(u)}.isFailure)
        Credentials.validate("https://example.com")
    }
    @Test fun loopbackOnlyInDebug() {
        val allowed=runCatching{Credentials.validate("http://127.0.0.1:8000")}.isSuccess
        assertEquals(BuildConfig.DEBUG,allowed)
    }
}
