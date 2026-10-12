package site.leospace.qdrop

import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import androidx.work.*
import kotlinx.coroutines.*
import org.json.JSONObject
import java.io.File
import java.time.Instant
import java.util.concurrent.TimeUnit

class Sender(private val context: Context) {
    private val tasks = QueueDb.get(context).tasks()
    suspend fun statuses() = withContext(Dispatchers.IO) {
        val api=Api(context)
        for(t in tasks.submitted()) if(t.serverId != null && t.state != "目标已收到") {
            try { val state=api.request("GET","/v1/transfers/${t.serverId}").getString("state")
                if(state in listOf("RECEIVED","EXPIRED","CANCELLED"))tasks.finish(t.id,when(state){"RECEIVED"->"目标已收到";"EXPIRED"->"已过期";else->"已取消"},null,t.serverId)
            }catch(e:ApiError){if(e.status in listOf(404,410))tasks.finish(t.id,"已过期",e.code,t.serverId)}catch(_:Exception){}
        }
    }
    suspend fun run(): Boolean = withContext(Dispatchers.IO) {
        val api = Api(context); var retry = false
        for (t in tasks.pending()) {
            val current = System.currentTimeMillis()
            if (tasks.claim(t.id, current, current + 360000) != 1) { retry = true; continue }
            var sid = t.serverId
            api.deadline = android.os.SystemClock.elapsedRealtime() + 300000
            try {
                val meta = JSONObject(t.metadata)
                if (meta.optString("sensitivity") == "sensitive" && current - t.created >= 300000) { tasks.finish(t.id, "已过期", "敏感文本超过发送有效期", sid); File(t.path).delete(); continue }
                if (sid == null) { sid = api.post("/v1/transfers", meta).getString("id"); tasks.server(t.id, sid) }
                val state = api.request("GET", "/v1/transfers/$sid").getString("state")
                if (state == "CREATED") api.put("/v1/transfers/$sid/content", File(t.path))
                val result = api.post("/v1/transfers/$sid/commit")
                val committed = System.currentTimeMillis()
                tasks.finish(t.id, if (result.getString("state") == "RECEIVED") "目标已收到" else "已暂存，等待目标接收", null, sid, committed)
                scheduleCleanup(context, t.id, cacheExpiry(t.copy(committed = committed)))
            } catch (e: ApiError) {
                val transient = e.retry || e.status in listOf(408, 429, 507)
                tasks.finish(t.id, if (transient) "等待重试" else if (e.status == 410) "已过期" else "需处理", e.message, sid)
                retry = retry || transient
                if (e.status == 429) delay(e.retryAfter.coerceIn(1, 300) * 1000)
                if (e.status == 401) break
            } catch (e: Exception) { tasks.finish(t.id, "等待重试", e.javaClass.simpleName, sid); retry = true }
            finally { api.deadline = Long.MAX_VALUE }
        }
        statuses()
        for (t in tasks.all()) {
            if (System.currentTimeMillis() >= cacheExpiry(t)) { File(t.path).delete(); if (t.committed == null && t.state in listOf("排队", "等待重试", "上传中")) tasks.finish(t.id, "已过期", "本地缓存到期，请重新分享", t.serverId) }
            else scheduleCleanup(context, t.id, cacheExpiry(t))
        }
        val known = tasks.all().map { it.path }.toSet()
        File(context.filesDir, "outbox").listFiles()?.filter { it.path !in known && System.currentTimeMillis() - it.lastModified() > 3600000 }?.forEach { it.delete() }
        retry
    }
}
fun cacheExpiry(t: SendTask): Long {
    val meta = JSONObject(t.metadata)
    return if(meta.optString("sensitivity") == "sensitive") t.created + 300000
    else if(meta.optString("kind") == "file" && t.committed != null) t.committed + 3600000
    else t.created + 86400000
}
fun scheduleCleanup(c: Context, id: String, expiry: Long) {
    val work = OneTimeWorkRequestBuilder<CacheCleanupWorker>().setInputData(workDataOf("task" to id)).setInitialDelay((expiry - System.currentTimeMillis()).coerceAtLeast(0), TimeUnit.MILLISECONDS).build()
    WorkManager.getInstance(c).enqueueUniqueWork("cache-$id", ExistingWorkPolicy.REPLACE, work)
}
class CacheCleanupWorker(c: Context, p: WorkerParameters) : CoroutineWorker(c, p) {
    override suspend fun doWork(): Result {
        val dao=QueueDb.get(applicationContext).tasks();val task=dao.get(inputData.getString("task") ?: return Result.success()) ?: return Result.success()
        if(System.currentTimeMillis() < cacheExpiry(task)) return Result.retry()
        if(task.leaseUntil > System.currentTimeMillis()) return Result.retry()
        if(File(task.path).exists() && !File(task.path).delete())return Result.retry()
        if(task.committed == null && task.state in listOf("排队","等待重试","上传中"))dao.finish(task.id,"已过期","本地缓存到期，请重新分享",task.serverId)
        return Result.success()
    }
}
fun schedule(context: Context) {
    val work = OneTimeWorkRequestBuilder<RetryWorker>().setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).build()
    WorkManager.getInstance(context).enqueueUniqueWork("upload-retry", ExistingWorkPolicy.KEEP, work)
}
class RetryWorker(c: Context, p: WorkerParameters) : CoroutineWorker(c, p) {
    override suspend fun doWork(): Result { val retry = Sender(applicationContext).run(); return if (retry && runAttemptCount < 4) Result.retry() else Result.success() }
}
class UploadService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var running = false
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java); nm.createNotificationChannel(NotificationChannel("upload", "发送进度", NotificationManager.IMPORTANCE_LOW))
        val pending = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        startForeground(1, Notification.Builder(this, "upload").setSmallIcon(android.R.drawable.stat_sys_upload).setContentTitle("QDrop 正在发送").setContentText("只在任务执行期间运行").setContentIntent(pending).build(), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        if (!running) { running = true; scope.launch { try { if (Sender(this@UploadService).run()) schedule(this@UploadService) } finally { stopForeground(STOP_FOREGROUND_REMOVE); stopSelf() } } }
        return START_NOT_STICKY
    }
    override fun onTimeout(startId: Int, fgsType: Int) { scope.cancel(); schedule(this); stopForeground(STOP_FOREGROUND_REMOVE); stopSelf() }
    override fun onDestroy() { scope.cancel(); super.onDestroy() }
}
