package site.leospace.qdrop

import android.content.Context
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

class ApiError(val status: Int, val code: String, val retry: Boolean, val retryAfter: Long = 60) : Exception("$status $code")
class Api(c: Context) {
    var deadline: Long = Long.MAX_VALUE
    val config = Credentials(c)
    val client = OkHttpClient.Builder().connectTimeout(20, TimeUnit.SECONDS).readTimeout(120, TimeUnit.SECONDS).writeTimeout(120, TimeUnit.SECONDS).callTimeout(300, TimeUnit.SECONDS).build()
    fun request(method: String, path: String, body: RequestBody? = null, authenticated: Boolean = true): JSONObject {
        Credentials.validate(config.url)
        val b = Request.Builder().url(config.url + path).method(method, body)
        if (authenticated) b.header("Authorization", "Bearer ${config.token}")
        val remaining = deadline - android.os.SystemClock.elapsedRealtime()
        if (remaining <= 0) throw java.io.IOException("TASK_TIMEOUT")
        val call = client.newCall(b.build())
        call.timeout().timeout(minOf(remaining, 300000), TimeUnit.MILLISECONDS)
        call.execute().use { r ->
            val text = r.body?.string().orEmpty()
            if (!r.isSuccessful) { val j = runCatching { JSONObject(text) }.getOrDefault(JSONObject()); throw ApiError(r.code, j.optString("code", "HTTP_ERROR"), j.optBoolean("retryable", r.code >= 500), r.header("Retry-After")?.toLongOrNull() ?: 60) }
            return JSONObject(text)
        }
    }
    fun post(path: String, j: JSONObject = JSONObject(), authenticated: Boolean = true) = request("POST", path, j.toString().toRequestBody("application/json".toMediaType()), authenticated)
    fun put(path: String, file: File) = request("PUT", path, file.asRequestBody("application/octet-stream".toMediaType()))
}
