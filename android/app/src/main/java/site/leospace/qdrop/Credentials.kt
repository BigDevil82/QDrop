package site.leospace.qdrop

import android.content.Context
import android.annotation.SuppressLint
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class Credentials(c: Context) {
    private val prefs = c.getSharedPreferences("config", Context.MODE_PRIVATE)
    // Registration must not report success before protected credentials are durably saved.
    @SuppressLint("ApplySharedPref", "UseKtx")
    private fun save(k: String, v: String) { check(prefs.edit().putString(k, v).commit()) { "配置写入失败" } }
    var url: String get() = prefs.getString("url", "")!!; set(v) { validate(v); save("url", v.trimEnd('/')) }
    var defaultTarget: String get() = prefs.getString("target", "")!!; set(v) { save("target", v) }
    var deviceId: String get() = prefs.getString("device", "")!!; set(v) { save("device", v) }
    var deviceCache: String get() = prefs.getString("devices", "[]")!!; set(v) { save("devices", v) }
    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        return ks.getKey("QDropCredential", null) as? SecretKey ?: KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder("QDropCredential", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    var token: String
        get() { val raw = prefs.getString("token", null) ?: return ""; val bytes = Base64.decode(raw, Base64.NO_WRAP); return Cipher.getInstance("AES/GCM/NoPadding").run { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12))); String(doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8) } }
        set(v) { val cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key()); save("token", Base64.encodeToString(cipher.iv + cipher.doFinal(v.toByteArray()), Base64.NO_WRAP)) }
    companion object {
        fun validate(url: String) {
            val u = java.net.URI(url)
            require(!u.host.isNullOrEmpty()) { "服务地址需要有效主机名" }
            require(u.rawUserInfo == null && u.query == null && u.fragment == null && (u.path.isNullOrEmpty() || u.path == "/")) { "服务地址只填写 origin" }
            require(u.scheme == "https" || (BuildConfig.DEBUG && u.scheme == "http" && u.host in listOf("127.0.0.1", "localhost"))) { "发布包只允许 HTTPS" }
        }
    }
}
