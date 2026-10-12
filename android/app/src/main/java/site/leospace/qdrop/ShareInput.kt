package site.leospace.qdrop

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.UUID

data class Prepared(val path: String, val name: String?, val mime: String, val size: Long, val sha: String, val kind: String)
object ShareInput {
    fun sharedText(intent: Intent): String? {
        @Suppress("DEPRECATION")
        val raw = intent.extras?.get(Intent.EXTRA_TEXT)
        val extra = when (raw) {
            is CharSequence -> raw.toString()
            is List<*> -> raw.filterIsInstance<CharSequence>().joinToString("\n")
            else -> null
        }?.takeIf { it.isNotEmpty() }
        return extra ?: intent.clipData?.let { clip ->
            (0 until clip.itemCount).mapNotNull { clip.getItemAt(it).text?.toString() }
                .distinct().joinToString("\n").takeIf { it.isNotEmpty() }
        }
    }
    fun uris(intent: Intent): List<Uri> {
        val result = linkedSetOf<Uri>()
        @Suppress("DEPRECATION")
        if (intent.action == Intent.ACTION_SEND_MULTIPLE) result.addAll(intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM).orEmpty())
        else { @Suppress("DEPRECATION") val uri = intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM); if (uri != null) result.add(uri) }
        intent.clipData?.let { clip -> for (i in 0 until clip.itemCount) clip.getItemAt(i).uri?.let { result.add(it) } }
        require(result.size <= 20) { "一次最多 20 个文件" }; return result.toList()
    }
    fun snapshot(c: Context, uri: Uri): Prepared {
        require(uri.scheme == "content") { "只接受源应用授权的 content URI，请重新分享" }
        var name = "file"
        c.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { if (it.moveToFirst()) name = it.getString(0) ?: name }
        val directory = File(c.filesDir, "outbox").apply { mkdirs() }; val file = File(directory, UUID.randomUUID().toString())
        val hash = MessageDigest.getInstance("SHA-256"); var size = 0L
        try {
            c.contentResolver.openInputStream(uri)?.use { input -> FileOutputStream(file).use { output ->
                val buffer = ByteArray(65536)
                while (true) { val n = input.read(buffer); if (n < 0) break; size += n; require(size <= 50L * 1024 * 1024) { "文件超过 50 MiB" }; hash.update(buffer, 0, n); output.write(buffer, 0, n) }
                output.fd.sync()
            } } ?: error("URI 无法读取，请从原 App 重新分享")
        } catch (e: Exception) { file.delete(); throw e }
        return Prepared(file.path, name.take(255), c.contentResolver.getType(uri) ?: "application/octet-stream", size, hash.digest().joinToString("") { "%02x".format(it) }, "file")
    }
    fun text(c: Context, text: String): Prepared {
        val bytes = text.toByteArray(Charsets.UTF_8); require(bytes.size <= 65536) { "文本超过 64 KiB" }
        val f = File(File(c.filesDir, "outbox").apply { mkdirs() }, UUID.randomUUID().toString())
        FileOutputStream(f).use { it.write(bytes); it.fd.sync() }
        return Prepared(f.path, null, "text/plain;charset=utf-8", bytes.size.toLong(), MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }, "text")
    }
}
