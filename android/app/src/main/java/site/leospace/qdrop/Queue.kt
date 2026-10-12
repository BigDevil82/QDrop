package site.leospace.qdrop

import android.content.Context
import androidx.room.*
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "tasks")
data class SendTask(@PrimaryKey val id: String, val target: String, val path: String, val metadata: String,
    val created: Long, val serverId: String? = null, val state: String = "排队", val error: String? = null, val leaseUntil: Long = 0, val committed: Long? = null)
@Dao
interface TaskDao {
    @Insert suspend fun insert(t: SendTask)
    @Query("SELECT * FROM tasks ORDER BY created DESC") fun observe(): Flow<List<SendTask>>
    @Query("SELECT * FROM tasks WHERE state IN ('排队','等待重试','上传中') ORDER BY created") suspend fun pending(): List<SendTask>
    @Query("UPDATE tasks SET leaseUntil=:until,state='上传中' WHERE id=:id AND leaseUntil<:now AND state IN ('排队','等待重试','上传中')") suspend fun claim(id: String, now: Long, until: Long): Int
    @Query("UPDATE tasks SET state=:state,error=:error,serverId=COALESCE(:serverId,serverId),leaseUntil=0,committed=COALESCE(:committed,committed) WHERE id=:id") suspend fun finish(id: String, state: String, error: String?, serverId: String?, committed: Long? = null)
    @Query("UPDATE tasks SET serverId=:serverId WHERE id=:id") suspend fun server(id: String, serverId: String)
    @Query("SELECT * FROM tasks WHERE state IN ('已暂存，等待目标接收','目标已收到')") suspend fun submitted(): List<SendTask>
    @Query("SELECT * FROM tasks") suspend fun all(): List<SendTask>
    @Query("SELECT * FROM tasks WHERE id=:id") suspend fun get(id: String): SendTask?
}
@Database(entities = [SendTask::class], version = 1, exportSchema = false)
abstract class QueueDb : RoomDatabase() {
    abstract fun tasks(): TaskDao
    companion object {
        @Volatile private var db: QueueDb? = null
        fun get(c: Context): QueueDb = db ?: synchronized(this) { db ?: Room.databaseBuilder(c.applicationContext, QueueDb::class.java, "queue.db").build().also { db = it } }
    }
}
