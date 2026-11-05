package com.fabio.celularwebcam

import org.json.JSONObject

/**
 * Configuracao atual da camera. E o mesmo objeto alterado pela tela do celular
 * e pelo programa do PC, entao os dois sempre mostram a mesma coisa.
 */
data class CamSettings(
    var cameraId: String = "",
    var width: Int = 1280,
    var height: Int = 720,
    var fps: Int = 30,
    /** Bits por segundo. 0 = automatico (calculado pela resolucao e FPS). */
    var bitrate: Int = 0,
    var zoom: Float = 1f,
    var ev: Int = 0,
    var torch: Boolean = false,
    var afAuto: Boolean = true,
    /** 0 = infinito, 1 = o mais perto possivel. */
    var focus: Float = 0f,
    var awb: String = "auto",
    var aeManual: Boolean = false,
    var iso: Int = 400,
    var shutterNs: Long = 16_666_666L,
    var aeLock: Boolean = false,
    var awbLock: Boolean = false,
    var lowLight: Boolean = false,
    var stab: Boolean = false,
    var audio: Boolean = false,
) {
    fun effectiveBitrate(): Int {
        if (bitrate > 0) return bitrate
        val bpp = 0.12 // bits por pixel; bom equilibrio entre qualidade e Wi-Fi
        val auto = width.toDouble() * height * fps * bpp
        return auto.toInt().coerceIn(2_000_000, 40_000_000)
    }

    fun toJson(): JSONObject = JSONObject().apply {
        put("camera", cameraId)
        put("width", width)
        put("height", height)
        put("fps", fps)
        put("bitrate", bitrate)
        put("zoom", zoom.toDouble())
        put("ev", ev)
        put("torch", torch)
        put("afAuto", afAuto)
        put("focus", focus.toDouble())
        put("awb", awb)
        put("aeManual", aeManual)
        put("iso", iso)
        put("shutterNs", shutterNs)
        put("aeLock", aeLock)
        put("awbLock", awbLock)
        put("lowLight", lowLight)
        put("stab", stab)
        put("audio", audio)
    }

    /** Aplica so as chaves presentes no JSON. */
    fun patch(j: JSONObject) {
        if (j.has("camera")) cameraId = j.getString("camera")
        if (j.has("width")) width = j.getInt("width")
        if (j.has("height")) height = j.getInt("height")
        if (j.has("fps")) fps = j.getInt("fps")
        if (j.has("bitrate")) bitrate = j.getInt("bitrate")
        if (j.has("zoom")) zoom = j.getDouble("zoom").toFloat()
        if (j.has("ev")) ev = j.getInt("ev")
        if (j.has("torch")) torch = j.getBoolean("torch")
        if (j.has("afAuto")) afAuto = j.getBoolean("afAuto")
        if (j.has("focus")) focus = j.getDouble("focus").toFloat()
        if (j.has("awb")) awb = j.getString("awb")
        if (j.has("aeManual")) aeManual = j.getBoolean("aeManual")
        if (j.has("iso")) iso = j.getInt("iso")
        if (j.has("shutterNs")) shutterNs = j.getLong("shutterNs")
        if (j.has("aeLock")) aeLock = j.getBoolean("aeLock")
        if (j.has("awbLock")) awbLock = j.getBoolean("awbLock")
        if (j.has("lowLight")) lowLight = j.getBoolean("lowLight")
        if (j.has("stab")) stab = j.getBoolean("stab")
        if (j.has("audio")) audio = j.getBoolean("audio")
    }

    /** Mudancas que exigem reabrir a sessao da camera e o encoder. */
    fun needsRestart(old: CamSettings): Boolean =
        cameraId != old.cameraId || width != old.width || height != old.height || fps != old.fps
}
