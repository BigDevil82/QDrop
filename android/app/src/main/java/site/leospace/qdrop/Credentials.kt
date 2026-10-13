package site.leospace.qdrop

import android.content.Context
import android.annotation.SuppressLint
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import java.net.InetAddress
import org.json.JSONArray
import org.json.JSONObject
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
    data class Profile(val targetId: String, val name: String, val url: String, val tokenCipher: String, val deviceId: String)
    private fun profiles(): MutableList<Profile> = runCatching {
        val a=JSONArray(prefs.getString("profiles", "[]"));MutableList(a.length()){i->a.getJSONObject(i).let { Profile(it.getString("target"),it.getString("name"),it.getString("url"),it.getString("token"),it.getString("device")) }}
    }.getOrDefault(mutableListOf())
    private fun saveProfiles(items: List<Profile>) {
        val a=JSONArray();items.forEach { a.put(JSONObject().put("target",it.targetId).put("name",it.name).put("url",it.url).put("token",it.tokenCipher).put("device",it.deviceId)) };save("profiles",a.toString())
    }
    /** Called after the one-time registration has found this hub's only Windows receiver. */
    fun rememberActiveTarget(targetId: String, name: String) {
        val encrypted=prefs.getString("token", "")!!;if(encrypted.isEmpty() || token.isEmpty())return
        val entry=Profile(targetId,name,url,encrypted,deviceId);val all=profiles().filter { it.targetId!=targetId }.toMutableList();all.add(entry);saveProfiles(all)
    }
    /** Switches only to a previously paired target; discovery never creates a new trust entry. */
    fun useDiscoveredTarget(targetId: String, discoveredUrl: String): Boolean {
        validate(discoveredUrl);val profile=profiles().firstOrNull { it.targetId==targetId } ?: return false
        save("url",discoveredUrl.trimEnd('/'));save("token",profile.tokenCipher);save("device",profile.deviceId);save("target",profile.targetId);return true
    }
    fun knowsTarget(targetId: String) = profiles().any { it.targetId==targetId }
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
            if (u.scheme == "https") return
            require(u.scheme == "http") { "服务地址只允许 HTTPS 或局域网 HTTP" }
            require(u.host.matches(Regex("\\d{1,3}(\\.\\d{1,3}){3}"))) { "HTTP 仅允许私有局域网 IP" }
            val address = runCatching { InetAddress.getByName(u.host) }.getOrNull()
            val octets=u.host.split('.').map { it.toInt() }
            val sharedAddress=octets[0]==100 && octets[1] in 64..127
            require(address != null && (address.isSiteLocalAddress || address.isLinkLocalAddress || address.isLoopbackAddress || sharedAddress)) { "HTTP 仅允许私有局域网 IP" }
        }
    }
}
