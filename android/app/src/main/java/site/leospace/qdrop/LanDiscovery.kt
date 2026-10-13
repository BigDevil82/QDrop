package site.leospace.qdrop

import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.NetworkInterface
import java.util.Collections
import java.util.UUID

/** A small, local-only discovery protocol.  It carries no credentials or content. */
data class LanTarget(val deviceId: String, val name: String, val baseUrl: String)

object LanDiscovery {
    private const val Port = 48735
    private const val Prefix = "QDROP/1 DISCOVER "

    fun find(timeoutMs: Int = 1200): List<LanTarget> {
        val nonce = UUID.randomUUID().toString()
        val request = (Prefix + nonce).toByteArray(Charsets.UTF_8)
        val found = linkedMapOf<String, LanTarget>()
        DatagramSocket().use { socket ->
            socket.broadcast = true
            socket.soTimeout = 180
            val destinations = linkedSetOf(InetAddress.getByName("255.255.255.255"))
            Collections.list(NetworkInterface.getNetworkInterfaces()).filter { it.isUp && !it.isLoopback }.forEach { network ->
                network.interfaceAddresses.mapNotNullTo(destinations) { it.broadcast }
            }
            destinations.forEach { address -> runCatching { socket.send(DatagramPacket(request, request.size, address, Port)) } }
            val deadline = System.currentTimeMillis() + timeoutMs
            val buffer = ByteArray(2048)
            while (System.currentTimeMillis() < deadline) {
                try {
                    val packet = DatagramPacket(buffer, buffer.size); socket.receive(packet)
                    val json = JSONObject(String(packet.data, packet.offset, packet.length, Charsets.UTF_8))
                    if (json.optInt("version") != 1 || json.optString("nonce") != nonce) continue
                    val id = json.getString("device_id"); val url = json.getString("base_url")
                    Credentials.validate(url)
                    found[id] = LanTarget(id, json.optString("name", "Windows"), url)
                } catch (_: java.net.SocketTimeoutException) { }
                catch (_: Exception) { }
            }
        }
        return found.values.toList()
    }
}
