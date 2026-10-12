package site.leospace.qdrop
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONObject
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
@RunWith(AndroidJUnit4::class)
class FixtureTest {
    @Test fun realProviderUnknownZeroInvalidAndLimit() {
        val c=InstrumentationRegistry.getInstrumentation().targetContext
        val authority=c.packageName+".probe"
        val base="content://$authority/"
        val zero=ShareInput.snapshot(c,android.net.Uri.parse(base+"zero"));assertEquals(0,zero.size);assertEquals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",zero.sha);java.io.File(zero.path).delete()
        val unknown=ShareInput.snapshot(c,android.net.Uri.parse(base+"unknown"));assertTrue(unknown.size>0);java.io.File(unknown.path).delete()
        assertTrue(runCatching{ShareInput.snapshot(c,android.net.Uri.parse(base+"invalid"))}.isFailure)
        assertTrue(runCatching{ShareInput.snapshot(c,android.net.Uri.parse(base+"too-large"))}.isFailure)
        for(n in listOf("zero","unknown","too-large"))c.contentResolver.delete(android.net.Uri.parse(base+n),null,null)
    }
    @Test fun streamAndClipDataDeduplicated() {
        val one=android.net.Uri.parse("content://fixture/one");val two=android.net.Uri.parse("content://fixture/two")
        val intent=android.content.Intent(android.content.Intent.ACTION_SEND_MULTIPLE).putParcelableArrayListExtra(android.content.Intent.EXTRA_STREAM,arrayListOf(one,two))
        intent.clipData=android.content.ClipData.newUri(InstrumentationRegistry.getInstrumentation().targetContext.contentResolver,"test",one)
        assertEquals(listOf(one,two),ShareInput.uris(intent))
    }
    @Test fun multipleImagesAndTextListPreparedTogether() {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val c=instrumentation.targetContext
        val base="content://${c.packageName}.probe/"
        val intent=android.content.Intent(c,MainActivity::class.java)
            .setAction(android.content.Intent.ACTION_SEND_MULTIPLE)
            .setType("image/*")
            .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
            .putParcelableArrayListExtra(android.content.Intent.EXTRA_STREAM,arrayListOf(android.net.Uri.parse(base+"unknown"),android.net.Uri.parse(base+"zero")))
            .putCharSequenceArrayListExtra(android.content.Intent.EXTRA_TEXT,arrayListOf<CharSequence>("中文附带文本","第二行 🌍"))
        assertEquals("中文附带文本\n第二行 🌍",ShareInput.sharedText(intent))
        val probe=java.io.File(c.filesDir,"share-probe.json");probe.delete()
        // HyperOS may deny an instrumented background Activity start; foreground our own app via shell first.
        instrumentation.uiAutomation.executeShellCommand("am start -W -n ${c.packageName}/site.leospace.qdrop.MainActivity").use { fd ->
            android.os.ParcelFileDescriptor.AutoCloseInputStream(fd).use { it.readBytes() }
        }
        val activity=instrumentation.startActivitySync(intent)
        try {
            val until=android.os.SystemClock.elapsedRealtime()+10000
            while(!probe.exists() && android.os.SystemClock.elapsedRealtime()<until)Thread.sleep(50)
            val j=JSONObject(probe.readText());assertEquals(3,j.getInt("count"))
            val items=j.getJSONArray("items")
            assertEquals(listOf("file","file","text"),(0 until items.length()).map{items.getJSONObject(it).getString("kind")})
            val expected="中文附带文本\n第二行 🌍".toByteArray()
            assertEquals(expected.size.toLong(),items.getJSONObject(2).getLong("size"))
            val sha=java.security.MessageDigest.getInstance("SHA-256").digest(expected).joinToString(""){"%02x".format(it)}
            assertEquals(sha,items.getJSONObject(2).getString("sha256"))
        } finally {instrumentation.runOnMainSync{activity.finish()}}
        val single=android.content.Intent(android.content.Intent.ACTION_SEND).putExtra(android.content.Intent.EXTRA_TEXT,"单条中文")
        assertEquals("单条中文",ShareInput.sharedText(single))
        val clip=android.content.Intent(android.content.Intent.ACTION_SEND);clip.clipData=android.content.ClipData.newPlainText("text","ClipData 文本")
        assertEquals("ClipData 文本",ShareInput.sharedText(clip))
    }
    @Test fun localEnrollmentWhenRequested() {
        val args=InstrumentationRegistry.getArguments()
        val code=args.getString("enrollment") ?: return
        val c=InstrumentationRegistry.getInstrumentation().targetContext
        val config=Credentials(c);config.url="http://127.0.0.1:8000"
        val result=Api(c).post("/v1/enroll",JSONObject().put("code",code).put("device_name",android.os.Build.MODEL).put("platform","android").put("client_version","0.1.0"),false)
        config.token=result.getString("token");config.deviceId=result.getString("device_id")
        assertEquals(config.deviceId,Api(c).request("GET","/v1/me").getString("device_id"))
    }
    @Test fun sharedFixtureAndPrivateQueue() {
        val c=InstrumentationRegistry.getInstrumentation().targetContext
        val j=JSONObject(c.assets.open("transfer.json").bufferedReader().readText())
        assertEquals(0,j.getLong("size"));assertEquals(64,j.getString("sha256").length);assertEquals("READY",j.getString("state"))
        val error=JSONObject(c.assets.open("error.json").bufferedReader().readText());assertEquals("IDEMPOTENCY_CONFLICT",error.getString("code"));assertFalse(error.getBoolean("retryable"))
        val text=ShareInput.text(c,"中文 URL https://example.com")
        assertEquals("中文 URL https://example.com",java.io.File(text.path).readText());java.io.File(text.path).delete()
    }
}
