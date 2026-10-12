package site.leospace.qdrop

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.*
import androidx.room.withTransaction
import org.json.JSONObject
import java.io.File
import java.time.Instant
import java.util.UUID

data class Device(val id: String, val name: String, val online: Boolean, val known: Boolean = true)
class ShareViewModel : ViewModel() {
    var prepared by mutableStateOf<List<Prepared>>(emptyList())
    var busy by mutableStateOf(false)
    var message by mutableStateOf("从系统分享或选择文件开始")
    var devices by mutableStateOf<List<Device>>(emptyList())
    var processed by mutableStateOf(false)
    var sent by mutableStateOf(false)
}
class MainActivity : ComponentActivity() {
    private lateinit var vm: ShareViewModel
    private val permission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }
    private val pick = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris -> if (uris.isNotEmpty()) prepare(uris, null) }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState); vm = ViewModelProvider(this)[ShareViewModel::class.java]
        if(vm.devices.isEmpty())runCatching{val a=org.json.JSONArray(Credentials(this).deviceCache);vm.devices=(0 until a.length()).mapNotNull{a.getJSONObject(it).let{d->if(d.getString("platform")=="windows")Device(d.getString("id"),d.getString("name"),false,false) else null}}}
        if (!vm.processed && savedInstanceState == null) { vm.processed = true; handle(intent) }
        schedule(this)
        setContent { MaterialTheme { Screen() } }
        refresh()
    }
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); vm.sent = false; handle(intent) }
    private fun handle(intent: Intent) {
        if (intent.action !in listOf(Intent.ACTION_SEND, Intent.ACTION_SEND_MULTIPLE)) return
        if(vm.busy){vm.message="上一项仍在准备，请完成后重新分享这项内容";return}
        try {
            prepare(ShareInput.uris(intent), ShareInput.sharedText(intent))
        }
        catch(e: Exception) { vm.prepared.forEach{File(it.path).delete()};vm.prepared=emptyList();vm.message = e.message ?: "无效分享" }
    }
    private fun prepare(uris: List<Uri>, text: String?) {
        if (vm.busy) return
        vm.prepared.forEach{File(it.path).delete()};vm.prepared=emptyList()
        vm.busy = true; vm.sent = false; vm.message = "正在授权有效期内复制私有快照，请暂时保持此页"
        lifecycleScope.launch {
            val prepared = mutableListOf<Prepared>()
            try {
                withContext(Dispatchers.IO) { require(uris.size <= 20) { "最多 20 个文件" }; for(u in uris) prepared.add(ShareInput.snapshot(this@MainActivity,u)); if(!text.isNullOrEmpty()) prepared.add(ShareInput.text(this@MainActivity,text)) }
                vm.prepared.forEach { File(it.path).delete() }; vm.prepared = prepared
                vm.message = "已读取分享并固定本地快照：${prepared.size} 项；点击目标即发送"
                // Local diagnostic only: no URI, text body, token, or original name.
                File(filesDir,"share-probe.json").writeText(JSONObject().put("count",prepared.size).put("items",org.json.JSONArray(prepared.map { JSONObject().put("kind",it.kind).put("size",it.size).put("sha256",it.sha) })).toString())
            } catch(e: Exception) { prepared.forEach { File(it.path).delete() }; vm.message = "读取失败: ${e.message}，请从原应用重新分享或选择文件" }
            finally { vm.busy = false }
        }
    }
    private fun refresh() {
        lifecycleScope.launch { try { val c=Credentials(this@MainActivity); if(c.token.isEmpty())return@launch; val result=withContext(Dispatchers.IO){val api=Api(this@MainActivity);check(api.request("GET","/v1/me").getInt("protocol_version")==1){"协议不兼容，请升级客户端"};api.request("GET","/v1/devices")}; val a=result.getJSONArray("devices");c.deviceCache=a.toString(); vm.devices=(0 until a.length()).mapNotNull{a.getJSONObject(it).let{d->if(d.getString("platform")=="windows")Device(d.getString("id"),d.getString("name"),d.getBoolean("online")) else null}}.sortedByDescending{it.id==c.defaultTarget};Sender(this@MainActivity).statuses() }catch(e:Exception){vm.message="设备查询失败，可向已缓存目标排队: ${e.message ?: e.javaClass.simpleName}"} }
    }
    private fun prepareText(text: String) {
        if(vm.busy)return
        vm.busy=true
        lifecycleScope.launch {
            try {
                require(text.isNotEmpty()) { "请输入文字" }
                val snapshot=withContext(Dispatchers.IO){ShareInput.text(this@MainActivity,text)}
                val previous=vm.prepared.filter{it.kind=="text"}
                vm.prepared=vm.prepared.filter{it.kind!="text"}+snapshot
                previous.forEach{File(it.path).delete()}
                vm.sent=false;vm.message="已准备 ${vm.prepared.size} 项（包含文字）；点击目标一起发送"
            }catch(e:Exception){vm.message="准备文字失败: ${e.message}"}
            finally{vm.busy=false}
        }
    }
    private fun send(device: Device, sensitive: Boolean) {
        if(vm.busy || vm.sent || vm.prepared.isEmpty())return
        vm.busy=true
        lifecycleScope.launch {
            try{
                val db=QueueDb.get(this@MainActivity);val dao=db.tasks();val batch=UUID.randomUUID().toString();val created=System.currentTimeMillis()
                db.withTransaction { for(p in vm.prepared){val id=UUID.randomUUID().toString();val j=JSONObject().put("client_transfer_id",id).put("recipient_device_id",device.id).put("kind",p.kind).put("name",p.name?:JSONObject.NULL).put("mime",p.mime).put("size",p.size).put("sha256",p.sha).put("sensitivity",if(sensitive && p.kind=="text")"sensitive" else "normal").put("requested_ttl_seconds",if(sensitive && p.kind=="text")300 else 86400).put("origin_created_at",Instant.ofEpochMilli(created).toString()).put("batch_id",batch)
                    dao.insert(SendTask(id,device.id,p.path,j.toString(),created)) } }
                dao.all().filter { it.created == created }.forEach { scheduleCleanup(this@MainActivity,it.id,cacheExpiry(it)) }
                vm.sent=true;vm.prepared=emptyList();Credentials(this@MainActivity).defaultTarget=device.id;schedule(this@MainActivity)
                try{startForegroundService(Intent(this@MainActivity,UploadService::class.java))}catch(e:Exception){vm.message="后台启动受限，任务已保存，将由系统补偿"}
                vm.message="任务已持久化，可以返回原 App；上传成功仍需目标 ACK"
            }catch(e:Exception){vm.message="保存任务失败: ${e.javaClass.simpleName}"}
            finally{vm.busy=false}
        }
    }
    @Composable private fun Screen() {
        val config=remember{Credentials(this)}
        var url by remember{mutableStateOf(config.url)};var code by remember{mutableStateOf("")};var name by remember{mutableStateOf(Build.MODEL)}
        var text by remember{mutableStateOf("")};var sensitive by remember{mutableStateOf(false)}
        var showSettings by remember{mutableStateOf(runCatching{config.token.isEmpty()}.getOrDefault(true))}
        val tasks by QueueDb.get(this).tasks().observe().collectAsState(initial=emptyList())
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),verticalArrangement=Arrangement.spacedBy(10.dp)) {
            Text("QDrop 0.1.0 · 手机发送",style=MaterialTheme.typography.headlineSmall)
            Text(vm.message)
            if(vm.prepared.isNotEmpty()){
                Row { Checkbox(sensitive,{sensitive=it});Text("敏感文本（5 分钟）") }
                vm.prepared.forEach{p->Text("${p.name?:"附带文本"} · ${p.size} 字节");if(p.kind=="text")Text(runCatching{File(p.path).readText().take(200)}.getOrDefault("快照不可用"))}
                vm.devices.forEach{d->Button(onClick={send(d,sensitive)},enabled=!vm.busy && !vm.sent){Text("${d.name} · ${if(!d.known)"状态未知，可排队" else if(d.online)"在线" else "离线可暂存"}${if(d.id==config.defaultTarget)" · 默认" else ""}")}}
            }
            Button(onClick={showSettings=!showSettings}){Text("设置 / 注册")}
            if(showSettings){
            OutlinedTextField(url,{url=it},label={Text("HTTPS 服务地址（debug 可本地回环）")})
            OutlinedTextField(code,{code=it},label={Text("一次性注册码")})
            OutlinedTextField(name,{name=it},label={Text("设备名")})
            Button(onClick={lifecycleScope.launch{try{config.url=url;val r=withContext(Dispatchers.IO){Api(this@MainActivity).post("/v1/enroll",JSONObject().put("code",code).put("device_name",name).put("platform","android").put("client_version","0.1.0"),false)};config.token=r.getString("token");config.deviceId=r.getString("device_id");code="";showSettings=false;vm.message="已注册";refresh()}catch(e:Exception){vm.message="注册失败: ${e.message}"}}}){Text("注册此手机")}
            Button(onClick={if(Build.VERSION.SDK_INT>=33)permission.launch(Manifest.permission.POST_NOTIFICATIONS)}){Text("允许传输通知")}
            }
            OutlinedTextField(text,{text=it},label={Text("文字 / URL（先准备，再点击目标发送）")})
            Row { Button(onClick={val clipboard=getSystemService(ClipboardManager::class.java);text=clipboard.primaryClip?.getItemAt(0)?.coerceToText(this@MainActivity)?.toString().orEmpty()}){Text("粘贴")};Spacer(Modifier.width(8.dp));Button(onClick={prepareText(text) },enabled=!vm.busy){Text(if(vm.prepared.any{it.kind=="file"})"附加文字" else "准备文字")} }
            Button(onClick={pick.launch(arrayOf("*/*"))},enabled=!vm.busy){Text("选择文件（系统选择器）")}
            Row { Checkbox(sensitive,{sensitive=it});Text("手动标记敏感文本（5 分钟）") }
            Button(onClick={refresh()}){Text("刷新设备 / 查询目标状态")}
            Button(onClick={schedule(this@MainActivity);lifecycleScope.launch{withContext(Dispatchers.IO){Sender(this@MainActivity).run()}}}){Text("重试队列 / 刷新回执")}
            Text("最近任务：接收与本地动作互相独立")
            tasks.take(50).forEach{t->Text("${t.id.take(8)} · ${t.state} ${t.error.orEmpty()}")}
            Text("仅任务执行期间使用前台服务。强制停止后请重新打开恢复；不承诺手机永久后台在线。通知拒绝时仍可在此查看任务。")
        }
    }
}
