package site.leospace.qdrop
import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import java.io.File
import java.io.RandomAccessFile

// Debug build only. Three private synthetic fixtures, no app/user files exposed.
class ProbeProvider : ContentProvider() {
    override fun onCreate() = true
    override fun getType(uri: Uri) = "application/octet-stream"
    override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor {
        val columns = projection ?: arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)
        return MatrixCursor(columns).apply { addRow(columns.map { if(it == OpenableColumns.DISPLAY_NAME) "中文未知大小.bin" else null }.toTypedArray()) }
    }
    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        require(mode == "r"); val name = uri.lastPathSegment ?: error("Unknown fixture")
        require(name in listOf("zero", "unknown", "too-large"))
        val file = File(context!!.cacheDir, "probe-$name")
        when(name) {
            "zero" -> file.writeBytes(byteArrayOf())
            "unknown" -> file.writeBytes("真实 ContentProvider，未知 size".toByteArray())
            else -> RandomAccessFile(file,"rw").use { it.setLength(50L*1024*1024+1) }
        }
        return ParcelFileDescriptor.open(file,ParcelFileDescriptor.MODE_READ_ONLY)
    }
    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?) = 0
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int {
        val name=uri.lastPathSegment
        return if(name in listOf("zero","unknown","too-large") && File(context!!.cacheDir,"probe-$name").delete())1 else 0
    }
}
