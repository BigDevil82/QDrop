using System.IO;
using System.IO.Pipes;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Data.Sqlite;
using Microsoft.Win32;
using Microsoft.Windows.AppNotifications;
using Microsoft.Windows.AppNotifications.Builder;
using Forms = System.Windows.Forms;
using Application = System.Windows.Application;
using Clipboard = System.Windows.Clipboard;
using TextBox = System.Windows.Controls.TextBox;
using ListBox = System.Windows.Controls.ListBox;
using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using MessageBox = System.Windows.MessageBox;

namespace QDrop;

public class Settings
{
    public string BaseUrl { get; set; } = "";
    public string Token { get; set; } = "";
    public string DeviceId { get; set; } = "";
    public string Directory { get; set; } = Paths.Downloads();
    public bool AutoCopy { get; set; } = true;
    public bool AutoOpen { get; set; } = true;
    public bool Startup { get; set; }
}
public sealed class ChecksumException : IOException { public ChecksumException() : base("SHA-256 mismatch") { } }
public static class Paths
{
    public static readonly string Root = Environment.GetEnvironmentVariable("QDROP_TEST_ROOT") ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "QDrop");
    [System.Runtime.InteropServices.DllImport("shell32.dll")] static extern int SHGetKnownFolderPath(ref Guid id, uint flags, IntPtr token, out IntPtr path);
    public static string Downloads()
    {
        var id = new Guid("374DE290-123F-4565-9164-39C4925E467B");
        var hr = SHGetKnownFolderPath(ref id, 0, IntPtr.Zero, out var ptr);
        if (hr != 0) throw new IOException("Downloads Known Folder unavailable");
        try { return Path.Combine(System.Runtime.InteropServices.Marshal.PtrToStringUni(ptr)!, "QDrop"); }
        finally { System.Runtime.InteropServices.Marshal.FreeCoTaskMem(ptr); }
    }
    public static string SafeName(string? name)
    {
        name = new string((name ?? "file").Select(c => Path.GetInvalidFileNameChars().Contains(c) || char.IsControl(c) ? '_' : c).ToArray()).TrimEnd(' ', '.');
        if (name.Length == 0) name = "file";
        var stem = name.Split('.')[0].TrimEnd(' ','.').Normalize(NormalizationForm.FormKC).ToUpperInvariant();
        if (new[] { "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9" }.Contains(stem)) name = "_" + name;
        if (name.Length > 100) name = name[..80] + Path.GetExtension(name)[..Math.Min(16, Path.GetExtension(name).Length)];
        return name;
    }
    public static string FinalPath(string root, string id, string? name)
    {
        id = Guid.Parse(id).ToString();
        var path = Path.GetFullPath(Path.Combine(root, id, SafeName(name)));
        if (!path.StartsWith(Path.GetFullPath(root) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new IOException("Unsafe path");
        return path;
    }
}
public partial class App : Application
{
    Settings settings = new();
    Forms.NotifyIcon tray = null!;
    Window window = null!;
    TextBox address = null!, code = null!, directory = null!;
    TextBlock status = null!;
    ListBox records = null!;
    readonly CancellationTokenSource stopping = new();
    readonly SemaphoreSlim sync = new(1);
    Mutex singleton = null!;
    string PipeName => "QDrop-"+Environment.UserName;
    HttpClient http = new() { Timeout = TimeSpan.FromMinutes(5) };
    bool locked;
    bool notifications;
    bool authFailed;
    DateTimeOffset serverOffsetAnchor;
    TimeSpan serverOffset;
    SqliteConnection db = null!;
    Process? localServer;
    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        singleton = new Mutex(true, "Local\\QDrop-"+Environment.UserName, out var first);
        if (!first)
        {
            if(e.Args.Any(a=>a.Contains("AppNotificationActivated")))
            {
                var forwarded=new TaskCompletionSource();
                AppNotificationManager.Default.NotificationInvoked+=async(_,a)=>{try{await Forward(a.Argument);}finally{forwarded.TrySetResult();}};
                try{AppNotificationManager.Default.Register();await Task.WhenAny(forwarded.Task,Task.Delay(10000));}catch{await Forward("show");}
            }
            else await Forward("show");
            Shutdown();return;
        }
        Directory.CreateDirectory(Paths.Root);
        try
        {
            var conf = Path.Combine(Paths.Root, "settings.bin");
            if (File.Exists(conf)) settings = JsonSerializer.Deserialize<Settings>(ProtectedData.Unprotect(File.ReadAllBytes(conf), null, DataProtectionScope.CurrentUser))!;
            StartBundledServer();
#if DEBUG
            if(e.Args.Contains("--integration-test") || e.Args.Contains("--local-setup")) settings=JsonSerializer.Deserialize<Settings>(File.ReadAllText(Environment.GetEnvironmentVariable("QDROP_TEST_CONFIG")!))!;
            if(e.Args.Contains("--local-setup"))Save();
#endif
            db = new SqliteConnection("Data Source="+Path.Combine(Paths.Root,"tasks.db")); db.Open();
            Exec("PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS received(id TEXT PRIMARY KEY,path TEXT NOT NULL,meta TEXT NOT NULL,ack INTEGER NOT NULL DEFAULT 0,action TEXT NOT NULL DEFAULT 'pending',error TEXT,expires TEXT); CREATE TABLE IF NOT EXISTS failures(id TEXT PRIMARY KEY,error TEXT NOT NULL,updated TEXT NOT NULL);");
            foreach(var column in new[]{("attempts","INTEGER NOT NULL DEFAULT 0"),("max_attempts","INTEGER NOT NULL DEFAULT 5")}){
                bool exists=false;using(var c=db.CreateCommand()){c.CommandText="PRAGMA table_info(failures)";using var r=c.ExecuteReader();while(r.Read())if(r.GetString(1)==column.Item1)exists=true;}
                if(!exists)Exec("ALTER TABLE failures ADD COLUMN "+column.Item1+" "+column.Item2);
            }
            SystemEvents.SessionSwitch += (_, args) => Dispatcher.BeginInvoke(()=>{
                if(args.Reason is SessionSwitchReason.SessionLock or SessionSwitchReason.SessionLogoff)locked=true;
                if(args.Reason==SessionSwitchReason.SessionUnlock){locked=false;_=Unlock();}
            });
            SystemEvents.PowerModeChanged += (_,args)=>{if(args.Mode==PowerModes.Resume)Dispatcher.BeginInvoke(()=>{_=Sync(true);});};
            locked = !SessionUnlocked();
            BuildWindow(); BuildTray();
            _=ActivationPipe();
            try
            {
                AppNotificationManager.Default.NotificationInvoked += (_,a) => Dispatcher.BeginInvoke(() => Activate(a.Argument));
                AppNotificationManager.Default.Register(); notifications=true;
            }
            catch (Exception ex) { Note("通知依赖未就绪: "+ex.GetType().Name); }
            if (e.Args.Contains("--self-test")) { await SelfTest(); Shutdown(); return; }
#if DEBUG
            if(e.Args.Contains("--integration-test")){if(e.Args.Contains("--recovery-marker"))await Copy("QDrop local recovery marker");await Sync(false);File.WriteAllText(Path.Combine(Paths.Root,"integration.json"),JsonSerializer.Serialize(new{status=status.Text,clipboard=Clipboard.ContainsText()?Clipboard.GetText():"",records=records.Items.Count}));Shutdown();return;}
#endif
            if (settings.Token.Length == 0) window.Show();
            _ = ReceiverLoop();
            _ = CompensationLoop();
            _ = LanDiscoveryLoop();
        }
        catch(Exception ex) { File.WriteAllText(Path.Combine(Paths.Root,"startup-error.txt"),ex.ToString()); MessageBox.Show(ex.GetType().Name+": "+ex.Message,"QDrop 启动失败"); Shutdown(1); }
    }
    async Task Forward(string argument)
    {
        try{using var pipe=new NamedPipeClientStream(".",PipeName,PipeDirection.Out,PipeOptions.Asynchronous);await pipe.ConnectAsync(3000);using var w=new StreamWriter(pipe){AutoFlush=true};await w.WriteLineAsync(argument);}catch{ }
    }
    async Task ActivationPipe()
    {
        while(!stopping.IsCancellationRequested)
        {
            try{using var pipe=new NamedPipeServerStream(PipeName,PipeDirection.In,1,PipeTransmissionMode.Byte,PipeOptions.Asynchronous|PipeOptions.CurrentUserOnly);await pipe.WaitForConnectionAsync(stopping.Token);using var r=new StreamReader(pipe);var arg=await r.ReadLineAsync(stopping.Token);if(arg?.Length<=1024)await Dispatcher.InvokeAsync(()=>{if(arg=="show")ShowWindow();else Activate(arg!);});}
            catch(OperationCanceledException){break;}catch{await Task.Delay(1000);}
        }
    }
    void Exec(string sql, params (string, object?)[] args)
    {
        using var c = db.CreateCommand(); c.CommandText=sql;
        foreach(var (k,v) in args)c.Parameters.AddWithValue(k,v??DBNull.Value);
        c.ExecuteNonQuery();
    }
    void Save()
    {
        ValidateUrl(settings.BaseUrl);
        var bytes=ProtectedData.Protect(JsonSerializer.SerializeToUtf8Bytes(settings),null,DataProtectionScope.CurrentUser);
        var target=Path.Combine(Paths.Root,"settings.bin");File.WriteAllBytes(target+".part",bytes);File.Move(target+".part",target,true);
        using var key=Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run");
        if(settings.Startup)key.SetValue("QDrop","\""+Environment.ProcessPath+"\"");else key.DeleteValue("QDrop",false);
    }
    static void ValidateUrl(string url)
    {
        var u=new Uri(url);
        if(u.UserInfo.Length>0 || u.Query.Length>0 || u.Fragment.Length>0 || u.AbsolutePath!="/")throw new ArgumentException("服务地址只填写 origin");
        if(u.Scheme=="https")return;
        if(u.Scheme=="http" && IPAddress.TryParse(u.Host, out var address) && (IPAddress.IsLoopback(address) || address.IsIPv6LinkLocal || address.IsIPv6SiteLocal || IsPrivateV4(address)))return;
        throw new ArgumentException("仅允许 HTTPS 或私有局域网 HTTP");
    }
    static bool IsPrivateV4(IPAddress address)
    {
        if(address.AddressFamily!=AddressFamily.InterNetwork)return false;
        var b=address.GetAddressBytes();return b[0]==10 || b[0]==127 || b[0]==192 && b[1]==168 || b[0]==172 && b[1]>=16 && b[1]<=31 || b[0]==100 && b[1]>=64 && b[1]<=127;
    }
    void BuildTray()
    {
        tray=new Forms.NotifyIcon { Icon=System.Drawing.SystemIcons.Application, Text="QDrop 接收器", Visible=true };
        var menu=new Forms.ContextMenuStrip();
        menu.Items.Add("设置与记录",null,(_,_)=>ShowWindow());
        menu.Items.Add("打开接收目录",null,(_,_)=> {Directory.CreateDirectory(settings.Directory);Open(settings.Directory);});
        menu.Items.Add("立即补收",null,async(_,_)=>await ManualSync());
        menu.Items.Add("显示局域网地址",null,(_,_)=>MessageBox.Show(LanBaseUrl() ?? "本机局域网服务未配置。请先将服务地址设为 http://127.0.0.1:8000 并启动本地服务。","QDrop 局域网地址"));
        menu.Items.Add("验证剪贴板与打开",null,async(_,_)=>await SelfTest());
        menu.Items.Add("退出",null,(_,_)=>Shutdown());
        tray.ContextMenuStrip=menu;tray.DoubleClick+=(_,_)=>ShowWindow();
    }
    void ShowWindow(){window.Show();window.Activate();}
    void BuildWindow()
    {
        window=new Window{Title="QDrop 0.1.0 · 一期接收器",Width=760,Height=650};
        window.Closing+=(_,a)=>{a.Cancel=true;window.Hide();};
        var p=new StackPanel{Margin=new Thickness(20)};window.Content=new ScrollViewer{Content=p};
        p.Children.Add(new TextBlock{Text="HTTPS 服务地址 / 一次性注册码 / 接收目录"});
        address=new TextBox{Text=settings.BaseUrl,Margin=new Thickness(0,8,0,0)};p.Children.Add(address);
        code=new TextBox{Margin=new Thickness(0,8,0,0)};p.Children.Add(code);
        directory=new TextBox{Text=settings.Directory,Margin=new Thickness(0,8,0,0)};p.Children.Add(directory);
        var copy=new CheckBox{Content="有效窗内自动复制文本（URL 仅复制）",IsChecked=settings.AutoCopy};p.Children.Add(copy);
        var open=new CheckBox{Content="有效窗内自动打开 PDF/TXT/常见图片",IsChecked=settings.AutoOpen};p.Children.Add(open);
        var startup=new CheckBox{Content="登录后启动",IsChecked=settings.Startup};p.Children.Add(startup);
        var save=new Button{Content="保存设置",Margin=new Thickness(0,8,0,0)};p.Children.Add(save);
        save.Click+=(_,_)=>{try{settings.BaseUrl=address.Text.TrimEnd('/');settings.Directory=Path.GetFullPath(directory.Text);settings.AutoCopy=copy.IsChecked==true;settings.AutoOpen=open.IsChecked==true;settings.Startup=startup.IsChecked==true;Save();Note("已保存");}catch(Exception ex){Note(ex.Message);}};
        var enroll=new Button{Content="注册这台电脑",Margin=new Thickness(0,8,0,0)};p.Children.Add(enroll);
        enroll.Click+=async(_,_)=>{
            try { settings.BaseUrl=address.Text.TrimEnd('/');ValidateUrl(settings.BaseUrl);using var response=await http.PostAsync(settings.BaseUrl+"/v1/enroll",Json(new{code=code.Text.Trim(),device_name=Environment.MachineName,platform="windows",client_version="0.1.0"}));response.EnsureSuccessStatusCode();var j=JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement;settings.Token=j.GetProperty("token").GetString()!;settings.DeviceId=j.GetProperty("device_id").GetString()!;code.Clear();authFailed=false;Save();Note("注册成功");await Sync(true); }
            catch(Exception ex){Note("注册失败: "+ex.GetType().Name);}
        };
        var localSetup=new Button{Content="初始化局域网并生成手机配对码",Margin=new Thickness(0,8,0,0)};p.Children.Add(localSetup);
        localSetup.Click+=async(_,_)=>await InitializeLan();
        status=new TextBlock{Text="等待连接",TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,12,0,12)};p.Children.Add(status);
        records=new ListBox{Height=250};p.Children.Add(records);
        var retry=new Button{Content="补收 / 重试 ACK"};p.Children.Add(retry);retry.Click+=async(_,_)=>await ManualSync();
        var manual=new Button{Content="手动打开或复制选中记录"};p.Children.Add(manual);manual.Click+=async(_,_)=>{if(records.SelectedItem is Record r)await Manual(r.Id);};
        Refresh();
    }
    record Record(string Id,string Summary){public override string ToString()=>Summary;}
    void Refresh()
    {
        if(records==null)return;records.Items.Clear();
        using var c=db.CreateCommand();c.CommandText="SELECT id,path,ack,action,error FROM received ORDER BY rowid DESC LIMIT 100";using var r=c.ExecuteReader();
        while(r.Read())records.Items.Add(new Record(r.GetString(0),$"{Path.GetFileName(r.GetString(1))} · {(r.GetInt32(2)==1?"已确认":r.GetInt32(2)==2?"已保存，确认迟到":"已保存，待 ACK")} · {r.GetString(3)} {(r.IsDBNull(4)?"":r.GetString(4))}"));
        r.Close();c.CommandText="SELECT id,error,attempts,max_attempts FROM failures ORDER BY updated DESC LIMIT 50";using var f=c.ExecuteReader();while(f.Read())records.Items.Add(new Record(f.GetString(0),$"{f.GetString(0)[..8]} · 接收未完成 · {f.GetString(1)} · {(f.GetInt32(2)>=f.GetInt32(3)?"等待手动重试":"待重试")}"));
    }
    void Note(string s){Dispatcher.Invoke(()=>{if(status!=null)status.Text=s;if(tray!=null){var label="QDrop · "+s;tray.Text=label[..Math.Min(63,label.Length)];}});}
    static StringContent Json(object value)=>new(JsonSerializer.Serialize(value),Encoding.UTF8,"application/json");
    async Task<HttpResponseMessage> Api(HttpMethod method,string path,object? body=null)
    {
        ValidateUrl(settings.BaseUrl);var req=new HttpRequestMessage(method,settings.BaseUrl+path);req.Headers.Authorization=new AuthenticationHeaderValue("Bearer",settings.Token);if(body!=null)req.Content=Json(body);
        var res=await http.SendAsync(req,HttpCompletionOption.ResponseHeadersRead,stopping.Token);
        if(res.StatusCode==System.Net.HttpStatusCode.Unauthorized){authFailed=true;res.Dispose();throw new UnauthorizedAccessException();}
        if(!res.IsSuccessStatusCode){var status=(int)res.StatusCode;res.Dispose();throw new HttpRequestException("API "+status,null,(System.Net.HttpStatusCode)status);}
        return res;
    }
    async Task<JsonElement> Get(string path){using var r=await Api(HttpMethod.Get,path);return JsonDocument.Parse(await r.Content.ReadAsStringAsync()).RootElement.Clone();}
    async Task ManualSync(){Exec("UPDATE failures SET attempts=0");await Sync(true);}
    static string Str(JsonElement t,string k)=>t.GetProperty(k).GetString()!;
    async Task Sync(bool catchup)
    {
        if(settings.Token.Length==0 || authFailed || !await sync.WaitAsync(0))return;
        try
        {
            var me=await Get("/v1/me");if(me.GetProperty("protocol_version").GetInt32()!=1)throw new InvalidOperationException("协议版本不兼容");
            serverOffset=DateTimeOffset.Parse(Str(me,"server_time"))-DateTimeOffset.UtcNow;serverOffsetAnchor=DateTimeOffset.UtcNow;
            await PurgeTexts();await RetryAcks();
            var items=new List<JsonElement>();string? cursor=null;
            do{var page=await Get("/v1/inbox"+(cursor==null?"":"?cursor="+Uri.EscapeDataString(cursor)));items.AddRange(page.GetProperty("items").EnumerateArray().Select(i=>i.Clone()));cursor=page.GetProperty("next_cursor").GetString();}while(cursor!=null);
            foreach(var t in items)
            {
                using(var c=db.CreateCommand()){c.CommandText="SELECT COUNT(*) FROM failures WHERE id=$id AND attempts>=max_attempts";c.Parameters.AddWithValue("$id",Str(t,"id"));if((long)c.ExecuteScalar()!>0)continue;}
                try{await Receive(t,catchup || items.Count>1);Exec("DELETE FROM failures WHERE id=$id",("$id",Str(t,"id")));}
                catch(Exception ex){Exec("INSERT INTO failures(id,error,updated,attempts,max_attempts) VALUES($id,$error,$time,1,$max) ON CONFLICT(id) DO UPDATE SET error=$error,updated=$time,attempts=failures.attempts+1,max_attempts=$max",("$id",Str(t,"id")),("$error",ex is ChecksumException?"SHA-256 不符":ex is IOException?"磁盘写入或数据长度错误":ex.GetType().Name),("$time",DateTimeOffset.UtcNow.ToString("O")),("$max",ex is ChecksumException?2:5));if(authFailed)throw;}
            }
            Note("在线 · 最近补收 "+DateTime.Now.ToString("HH:mm:ss"));Refresh();
        }
        catch(Exception ex){Note(authFailed?"凭证失效，请重新注册":"接收等待重试: "+ex.GetType().Name);}
        finally{sync.Release();}
    }
    async Task Receive(JsonElement t,bool catchup)
    {
        var id=Guid.Parse(Str(t,"id")).ToString();var text=Str(t,"kind")=="text";
        using(var c=db.CreateCommand()){c.CommandText="SELECT COUNT(*) FROM received WHERE id=$id";c.Parameters.AddWithValue("$id",id);if((long)c.ExecuteScalar()!>0)return;}
        var path=Paths.FinalPath(text?Path.Combine(Paths.Root,"texts"):settings.Directory,id,text?"text.txt":t.GetProperty("name").GetString());
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var size=t.GetProperty("size").GetInt64();if(size>(text?65536:52428800) || size<0)throw new IOException("超出接收上限");
        var expected=Str(t,"sha256");
        if(!File.Exists(path) || await Hash(path)!=expected)
        {
            var part=path+".part";
            try{
                using var response=await Api(HttpMethod.Get,$"/v1/transfers/{id}/content");await using var input=await response.Content.ReadAsStreamAsync();
                using(var output=new FileStream(part,FileMode.Create,FileAccess.Write,FileShare.None,65536,true)){
                    byte[] bytes=new byte[65536];long count=0;int n;while((n=await input.ReadAsync(bytes,stopping.Token))>0){count+=n;if(count>size)throw new IOException("大小不符");await output.WriteAsync(bytes.AsMemory(0,n),stopping.Token);}if(count!=size)throw new IOException("大小不符");output.Flush(true);
                }
                if(await Hash(part)!=expected)throw new ChecksumException();File.Move(part,path,false);
            }finally{if(File.Exists(part))File.Delete(part);}
        }
        var expiry=DateTimeOffset.Parse(Str(t,"committed_at")).AddSeconds(Str(t,"sensitivity")=="sensitive"?300:86400);
        var serverExpiry=DateTimeOffset.Parse(Str(t,"expires_at"));if(serverExpiry<expiry)expiry=serverExpiry;
        Exec("INSERT OR IGNORE INTO received(id,path,meta,expires) VALUES($id,$path,$meta,$expiry)",("$id",id),("$path",path),("$meta",t.GetRawText()),("$expiry",expiry.ToString("O")));
        await RetryAcks(id);
        var timely=DateTimeOffset.UtcNow+serverOffset<DateTimeOffset.Parse(Str(t,"auto_action_until"));
        var allowed=text?settings.AutoCopy:settings.AutoOpen && new[]{".pdf",".txt",".png",".jpg",".jpeg",".webp"}.Contains(Path.GetExtension(path).ToLowerInvariant());
        if(!catchup && timely && allowed && (locked || !SessionUnlocked()))Exec("UPDATE received SET error='锁屏，等待解锁后检查有效窗' WHERE id=$id",("$id",id));
        else if(!catchup && !locked && SessionUnlocked() && timely && allowed)await Action(id,path,text);
        else Exec("UPDATE received SET action='skipped',error=$reason WHERE id=$id AND action='pending'",("$id",id),("$reason",catchup?"离线或批量补收，仅保存":!timely?"自动动作已过期":"锁屏或规则禁止自动动作"));
        Notify(id,text?"文本已保存":"文件已保存",Path.GetFileName(path));
    }
    async Task Unlock()
    {
        await Sync(true);
        if(locked || !SessionUnlocked() || !await sync.WaitAsync(0))return;
        try{
            var pending=new List<(string Id,string Path,JsonElement Meta)>();
            using(var c=db.CreateCommand()){c.CommandText="SELECT id,path,meta FROM received WHERE action='pending' AND ack!=0 ORDER BY rowid DESC";using var r=c.ExecuteReader();while(r.Read())pending.Add((r.GetString(0),r.GetString(1),JsonDocument.Parse(r.GetString(2)).RootElement.Clone()));}
            bool textUsed=false;var fileCount=pending.Count(p=>Str(p.Meta,"kind")=="file");
            foreach(var p in pending){var text=Str(p.Meta,"kind")=="text";var timely=DateTimeOffset.UtcNow+serverOffset<DateTimeOffset.Parse(Str(p.Meta,"auto_action_until"));
                var allowed=text?settings.AutoCopy&&!textUsed:settings.AutoOpen&&fileCount==1&&new[]{".pdf",".txt",".png",".jpg",".jpeg",".webp"}.Contains(Path.GetExtension(p.Path).ToLowerInvariant());
                if(timely && allowed){await Action(p.Id,p.Path,text);if(text)textUsed=true;}
                else Exec("UPDATE received SET action='skipped',error='解锁时已过期或批量动作被抑制' WHERE id=$id AND action='pending'",("$id",p.Id));
            }
            Refresh();
        }finally{sync.Release();}
    }
    static async Task<string> Hash(string path){using var f=File.OpenRead(path);return Convert.ToHexString(await SHA256.HashDataAsync(f)).ToLowerInvariant();}
    async Task RetryAcks(string? onlyId=null)
    {
        var rows=new List<(string,JsonElement)>();
        using(var c=db.CreateCommand()){c.CommandText="SELECT id,meta FROM received WHERE ack=0"+(onlyId==null?"":" AND id=$id");if(onlyId!=null)c.Parameters.AddWithValue("$id",onlyId);using var r=c.ExecuteReader();while(r.Read())rows.Add((r.GetString(0),JsonDocument.Parse(r.GetString(1)).RootElement.Clone()));}
        foreach(var (id,t) in rows)
        {
            try{using var res=await Api(HttpMethod.Post,$"/v1/transfers/{id}/ack",new{size=t.GetProperty("size").GetInt64(),sha256=Str(t,"sha256")});Exec("UPDATE received SET ack=1,error=NULL WHERE id=$id",("$id",id));}
            catch(HttpRequestException e)when(e.StatusCode==System.Net.HttpStatusCode.Gone){Exec("UPDATE received SET ack=2,error='已保存，确认迟到' WHERE id=$id",("$id",id));}
            catch(HttpRequestException e)when(e.StatusCode is System.Net.HttpStatusCode.Forbidden or System.Net.HttpStatusCode.NotFound or System.Net.HttpStatusCode.UnprocessableEntity){Exec("UPDATE received SET ack=2,error='已保存，ACK 权限/元数据需处理' WHERE id=$id",("$id",id));}
            catch(HttpRequestException){Exec("UPDATE received SET error='已保存，ACK 等待重试' WHERE id=$id",("$id",id));}
        }
    }
    async Task PurgeTexts()
    {
        var dead=new List<(string,string)>();using(var c=db.CreateCommand()){c.CommandText="SELECT id,path,meta,expires FROM received WHERE meta!='{}'";using var r=c.ExecuteReader();while(r.Read()){var t=JsonDocument.Parse(r.GetString(2)).RootElement;if(Str(t,"kind")=="text" && DateTimeOffset.Parse(r.GetString(3))<=DateTimeOffset.UtcNow+serverOffset)dead.Add((r.GetString(0),r.GetString(1)));}}
        foreach(var(id,path)in dead){File.Delete(path);Exec("UPDATE received SET action='skipped',error='文本正文已到期' WHERE id=$id",("$id",id));}
        await Task.CompletedTask;
    }
    async Task Action(string id,string path,bool text)
    {
        Exec("UPDATE received SET action='attempted' WHERE id=$id AND action='pending'",("$id",id));
        try{if(text)await Copy(await DecodeText(path));else Open(path);Exec("UPDATE received SET action='succeeded',error=NULL WHERE id=$id",("$id",id));}
        catch(Exception ex){Exec("UPDATE received SET action='failed',error=$error WHERE id=$id",("$id",id),("$error",ex.GetType().Name));}
    }
    static void Open(string path)=>System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(path){UseShellExecute=true});
    static async Task<string> DecodeText(string path)=>new UTF8Encoding(false,true).GetString(await File.ReadAllBytesAsync(path));
    async Task Copy(string text)
    {
        if(text.Contains('\0'))throw new ArgumentException("剪贴板纯文本格式不支持 NUL 字符");
        foreach(int delay in new[]{0,50,100,200,400,800}){await Task.Delay(delay);try{await Dispatcher.InvokeAsync(()=>Clipboard.SetText(text));return;}catch(System.Runtime.InteropServices.COMException){}}
        throw new IOException("剪贴板被占用");
    }
    async Task Manual(string id)
    {
        using var c=db.CreateCommand();c.CommandText="SELECT path,meta FROM received WHERE id=$id";c.Parameters.AddWithValue("$id",id);using var r=c.ExecuteReader();if(!r.Read())return;var path=r.GetString(0);var text=Str(JsonDocument.Parse(r.GetString(1)).RootElement,"kind")=="text";
        try{if(text)await Copy(await DecodeText(path));else Open(path);}catch(Exception ex){Note("本地动作失败: "+ex.GetType().Name);}
    }
    void Notify(string id,string title,string name)
    {
        if(!notifications){tray.ShowBalloonTip(3000,title,"已保存，请在记录中打开或复制",Forms.ToolTipIcon.Info);return;}
        try{var builder=new AppNotificationBuilder().AddText(title).AddText(name).AddButton(new AppNotificationButton("打开/复制").AddArgument("id",id)).AddButton(new AppNotificationButton("目录").AddArgument("folder",id));AppNotificationManager.Default.Show(builder.BuildNotification());}catch(Exception ex){Note("通知失败: "+ex.GetType().Name);}
    }
    async void Activate(string args)
    {
        File.WriteAllText(Path.Combine(Paths.Root,"notification-activation.json"),JsonSerializer.Serialize(new{utc=DateTimeOffset.UtcNow,activated=true}));
        foreach(var kv in args.Split('&')){var pair=kv.Split('=');if(pair.Length!=2 || !Guid.TryParse(pair[1],out var id))continue;if(pair[0]=="id")await Manual(id.ToString());if(pair[0]=="folder")Open(settings.Directory);}
        ShowWindow();
    }
    async Task ReceiverLoop()
    {
        int retry=0;
        while(!stopping.IsCancellationRequested)
        {
            if(settings.Token.Length==0 || authFailed){await Task.Delay(1000);continue;}
            try{
                ValidateUrl(settings.BaseUrl);using var ws=new ClientWebSocket();ws.Options.SetRequestHeader("Authorization","Bearer "+settings.Token);var uri=new UriBuilder(settings.BaseUrl+"/v1/events");uri.Scheme=uri.Scheme=="https"?"wss":"ws";
                await ws.ConnectAsync(uri.Uri,stopping.Token);await Sync(true);retry=0;
                using var heartbeatStop=CancellationTokenSource.CreateLinkedTokenSource(stopping.Token);
                var heartbeat=Task.Run(async()=>{try{while(ws.State==WebSocketState.Open){await Task.Delay(30000,heartbeatStop.Token);await ws.SendAsync(Encoding.UTF8.GetBytes("heartbeat"),WebSocketMessageType.Text,true,heartbeatStop.Token);}}catch{ws.Abort();}});
                try{var buffer=new byte[4096];while(ws.State==WebSocketState.Open){var result=await ws.ReceiveAsync(buffer,stopping.Token);if(result.MessageType==WebSocketMessageType.Close)break;await Sync(false);}}
                finally{heartbeatStop.Cancel();await heartbeat;}
            }
            catch(Exception ex){Note("离线: "+ex.GetType().Name);}
            await Task.Delay(TimeSpan.FromSeconds(Math.Min(30,Math.Pow(2,Math.Min(++retry,5)))+Random.Shared.NextDouble()),stopping.Token);
        }
    }
    async Task CompensationLoop(){while(!stopping.IsCancellationRequested){try{await Task.Delay(60000,stopping.Token);await PurgeTexts();await Sync(true);}catch(OperationCanceledException){break;}catch(Exception ex){Note("清理/补收等待重试: "+ex.GetType().Name);}}}
    string BundledRoot()=>Path.Combine(AppContext.BaseDirectory,"local-server");
    void StartBundledServer()
    {
        var root=BundledRoot();var python=Path.Combine(root,"python","python.exe");var server=Path.Combine(root,"server");
        if(!File.Exists(python) || !File.Exists(Path.Combine(server,"app","main.py")))return;
        if(string.IsNullOrWhiteSpace(settings.BaseUrl))settings.BaseUrl="http://127.0.0.1:8000";
        var start=new ProcessStartInfo(python){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=root};
        foreach(var arg in new[]{"-m","uvicorn","app.main:app","--app-dir",server,"--host","0.0.0.0","--port","8000","--workers","1","--no-access-log","--no-proxy-headers"})start.ArgumentList.Add(arg);
        start.Environment["DATA_DIR"]=Path.Combine(Paths.Root,"server-data");start.Environment["PYTHONPATH"]=server+Path.PathSeparator+Path.Combine(root,"site-packages");
        localServer=Process.Start(start);
    }
    string CreateEnrollmentCode()
    {
        var root=BundledRoot();var python=Path.Combine(root,"python","python.exe");var server=Path.Combine(root,"server");
        if(!File.Exists(python))throw new FileNotFoundException("安装包缺少本地服务运行时",python);
        var start=new ProcessStartInfo(python){UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,WorkingDirectory=root};
        foreach(var arg in new[]{"-m","app.cli","enroll"})start.ArgumentList.Add(arg);
        start.Environment["DATA_DIR"]=Path.Combine(Paths.Root,"server-data");start.Environment["PYTHONPATH"]=server+Path.PathSeparator+Path.Combine(root,"site-packages");
        using var process=Process.Start(start)!;var output=process.StandardOutput.ReadToEnd();var error=process.StandardError.ReadToEnd();process.WaitForExit();
        if(process.ExitCode!=0)throw new IOException("生成配对码失败: "+error.Trim());return output.Trim();
    }
    async Task InitializeLan()
    {
        try
        {
            settings.BaseUrl="http://127.0.0.1:8000";address.Text=settings.BaseUrl;
            var serverReady=false;for(var i=0;i<30;i++){try{using var ready=await http.GetAsync(settings.BaseUrl+"/readyz");if(ready.IsSuccessStatusCode){serverReady=true;break;}}catch when(i<29){}await Task.Delay(200);}if(!serverReady)throw new IOException("本地服务未能启动");
            var localIdentityValid=false;
            if(settings.Token.Length>0)
            {
                try{using var check=new HttpRequestMessage(HttpMethod.Get,settings.BaseUrl+"/v1/me");check.Headers.Authorization=new AuthenticationHeaderValue("Bearer",settings.Token);using var response=await http.SendAsync(check);localIdentityValid=response.IsSuccessStatusCode;}catch{}
            }
            if(!localIdentityValid)
            {
                var own=CreateEnrollmentCode();using var response=await http.PostAsync(settings.BaseUrl+"/v1/enroll",Json(new{code=own,device_name=Environment.MachineName,platform="windows",client_version="0.1.0"}));response.EnsureSuccessStatusCode();
                var j=JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement;settings.Token=j.GetProperty("token").GetString()!;settings.DeviceId=j.GetProperty("device_id").GetString()!;authFailed=false;Save();
            }
            var phone=CreateEnrollmentCode();var lan=LanBaseUrl()??throw new IOException("没有可用的局域网 IPv4 地址");
            MessageBox.Show("手机服务地址："+lan+"\n\n一次性注册码："+phone+"\n\n请在 10 分钟内完成手机注册。","QDrop 手机配对");Note("局域网服务已就绪");
        }
        catch(Exception ex){Note("局域网初始化失败: "+ex.GetType().Name);MessageBox.Show(ex.Message,"QDrop 局域网初始化失败");}
    }
    async Task LanDiscoveryLoop()
    {
        // Discovery only returns a LAN address and device identity. Credentials stay in HTTPS/HTTP API headers.
        try
        {
            using var udp=new UdpClient(48735); udp.EnableBroadcast=true;
            while(!stopping.IsCancellationRequested)
            {
                var received=await udp.ReceiveAsync(stopping.Token);var request=Encoding.UTF8.GetString(received.Buffer);
                const string prefix="QDROP/1 DISCOVER ";if(!request.StartsWith(prefix,StringComparison.Ordinal) || settings.Token.Length==0 || !Guid.TryParse(settings.DeviceId,out _))continue;
                var nonce=request[prefix.Length..].Trim();if(!Guid.TryParse(nonce,out _))continue;
                var url=LanBaseUrl(received.RemoteEndPoint.Address);if(url==null)continue;
                var body=Encoding.UTF8.GetBytes(JsonSerializer.Serialize(new{version=1,nonce,device_id=settings.DeviceId,name=Environment.MachineName,base_url=url}));
                await udp.SendAsync(body,body.Length,received.RemoteEndPoint);
            }
        }
        catch(OperationCanceledException){}
        catch(Exception ex){Note("局域网发现不可用: "+ex.GetType().Name);}
    }
    string? LanBaseUrl(IPAddress? peer=null)
    {
        if(!Uri.TryCreate(settings.BaseUrl,UriKind.Absolute,out var configured) || configured.Scheme!="http")return null;
        if(!IPAddress.TryParse(configured.Host,out var existing) || !IPAddress.IsLoopback(existing))return configured.ToString().TrimEnd('/');
        IPAddress? address=null;
        if(peer?.AddressFamily==AddressFamily.InterNetwork && !IPAddress.IsLoopback(peer))
        {
            try{using var route=new Socket(AddressFamily.InterNetwork,SocketType.Dgram,ProtocolType.Udp);route.Connect(new IPEndPoint(peer,9));address=((IPEndPoint)route.LocalEndPoint!).Address;}catch(SocketException){}
        }
        address??=NetworkInterface.GetAllNetworkInterfaces().Where(n=>n.OperationalStatus==OperationalStatus.Up && n.NetworkInterfaceType is NetworkInterfaceType.Wireless80211 or NetworkInterfaceType.Ethernet && n.GetIPProperties().GatewayAddresses.Any(g=>g.Address.AddressFamily==AddressFamily.InterNetwork))
            .SelectMany(n=>n.GetIPProperties().UnicastAddresses).Select(a=>a.Address).FirstOrDefault(IsPrivateV4);
        return address==null?null:$"http://{address}:{configured.Port}";
    }
    [System.Runtime.InteropServices.DllImport("wtsapi32.dll")]static extern bool WTSQuerySessionInformation(IntPtr server,int session,int info,out IntPtr buffer,out int bytes);
    [System.Runtime.InteropServices.DllImport("wtsapi32.dll")]static extern void WTSFreeMemory(IntPtr p);
    static bool SessionUnlocked()
    {
        // WTSINFOEX level 1: DWORD level, alignment, sessionId, state, flags (0 locked / 1 unlocked on Windows 10+).
        if(!WTSQuerySessionInformation(IntPtr.Zero,System.Diagnostics.Process.GetCurrentProcess().SessionId,25,out var p,out var size))return false;
        try{return size>=20 && System.Runtime.InteropServices.Marshal.ReadInt32(p,0)==1 && System.Runtime.InteropServices.Marshal.ReadInt32(p,16)==1;}finally{WTSFreeMemory(p);}
    }
    async Task SelfTest()
    {
        var report=new Dictionary<string,object>();
        try{
            var fixture=JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory,"protocol-transfer.json"))).RootElement;
            report["fixture"]=Guid.TryParse(Str(fixture,"id"),out _) && fixture.GetProperty("size").GetInt64()==0;
            var errorFixture=JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory,"protocol-error.json"))).RootElement;report["fixture_error"]=Str(errorFixture,"code")=="IDEMPOTENCY_CONFLICT"&&!errorFixture.GetProperty("retryable").GetBoolean();
            report["safe_names"]=new[]{"../a.txt","CON","中文.txt","a.ps1","a/../../b"}.All(n=>Paths.FinalPath(Paths.Root,Guid.NewGuid().ToString(),n).StartsWith(Paths.Root));
            var original=Clipboard.ContainsText()?Clipboard.GetText():null;
            await Copy("QDrop 阶段零剪贴板测试 https://example.com");report["clipboard"]=Clipboard.GetText()=="QDrop 阶段零剪贴板测试 https://example.com";
            if(original!=null)await Copy(original);
            var file=Path.Combine(Paths.Root,"stage-zero.txt");await File.WriteAllTextAsync(file,"QDrop 阶段零：文件关联打开验证\n");Open(file);report["file_association_launch"]=true;
            report["tray_created"]=tray.Visible;report["notification_registered"]=notifications;
            if(notifications){var n=new AppNotificationBuilder().AddText("QDrop 阶段零通知").AddText("请点击验证激活，安装环境需另行验收").BuildNotification();AppNotificationManager.Default.Show(n);report["notification_submitted"]=n.Id!=0;}
            window.Show();window.Close();report["close_hides"]=!window.IsVisible && tray.Visible;
            report["utc"]=DateTimeOffset.UtcNow;
        }catch(Exception ex){report["error"]=ex.GetType().Name+": "+ex.Message;}
        File.WriteAllText(Path.Combine(Paths.Root,"self-test.json"),JsonSerializer.Serialize(report,new JsonSerializerOptions{WriteIndented=true}));Note("平台验证记录: "+Path.Combine(Paths.Root,"self-test.json"));
    }
    protected override void OnExit(ExitEventArgs e)
    {
        stopping.Cancel();if(localServer is {HasExited:false}){localServer.Kill(true);localServer.WaitForExit(3000);}localServer?.Dispose();tray?.Dispose();if(notifications)AppNotificationManager.Default.Unregister();db?.Dispose();http.Dispose();singleton?.Dispose();base.OnExit(e);
    }
}
