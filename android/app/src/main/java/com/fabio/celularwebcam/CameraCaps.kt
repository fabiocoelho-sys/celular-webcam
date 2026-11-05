package com.fabio.celularwebcam

import android.content.Context
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CameraMetadata
import android.media.MediaCodec
import android.media.MediaCodecList
import android.media.MediaFormat
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject

/** Tudo o que uma camera do celular sabe fazer (resolucoes, FPS, zoom, foco...). */
class CameraCaps(
    val id: String,
    val facing: String,
    val label: String,
    val sensorOrientation: Int,
    /** Cada item: largura, altura, FPS maximo nessa resolucao. */
    val sizes: List<IntArray>,
    /** Faixas de FPS do auto-exposicao: [min, max]. */
    val fpsRanges: List<IntArray>,
    val zoomMin: Float,
    val zoomMax: Float,
    val zoomByRatio: Boolean,
    val evMin: Int,
    val evMax: Int,
    val evStep: Float,
    val hasFlash: Boolean,
    val manualSensor: Boolean,
    val isoMin: Int,
    val isoMax: Int,
    val expMinNs: Long,
    val expMaxNs: Long,
    val minFocusDist: Float,
    val afModes: Set<Int>,
    val awbModes: List<String>,
    val stabilization: Boolean,
    val lowLightBoost: Boolean,
) {
    /**
     * Lista de FPS que fazem sentido oferecer para uma resolucao: so o que a camera
     * libera no modo normal. (O modo de alta velocidade, 120/240 FPS, foi testado no
     * Galaxy S9 e trava o encoder; alem disso escurece a imagem.)
     */
    fun fpsOptions(w: Int, h: Int): List<Int> {
        val maxForSize = sizes.firstOrNull { it[0] == w && it[1] == h }?.get(2) ?: 30
        return fpsRanges.map { it[1] }.filter { it in 10..maxForSize }.distinct().sorted()
    }

    fun toJson(): JSONObject = JSONObject().apply {
        put("id", id)
        put("facing", facing)
        put("label", label)
        val all = mutableSetOf<Int>()
        put("sizes", JSONArray().apply {
            sizes.forEach {
                val opts = fpsOptions(it[0], it[1])
                all += opts
                put(JSONArray(listOf(it[0], it[1], opts.maxOrNull() ?: it[2], JSONArray(opts))))
            }
        })
        put("fps", JSONArray(all.sorted()))
        put("zoomMin", zoomMin.toDouble())
        put("zoomMax", zoomMax.toDouble())
        put("evMin", evMin)
        put("evMax", evMax)
        put("evStep", evStep.toDouble())
        put("flash", hasFlash)
        put("manual", manualSensor)
        put("isoMin", isoMin)
        put("isoMax", isoMax)
        put("expMinNs", expMinNs)
        put("expMaxNs", expMaxNs)
        put("focus", minFocusDist > 0f)
        put("awb", JSONArray(awbModes))
        put("stab", stabilization)
        put("lowLight", lowLightBoost)
    }

    companion object {
        // CONTROL_AE_MODE_ON_LOW_LIGHT_BOOST_BRIGHTNESS_PRIORITY (Android 15)
        const val AE_MODE_LOW_LIGHT_BOOST = 6

        val AWB_NAMES = linkedMapOf(
            CameraMetadata.CONTROL_AWB_MODE_AUTO to "auto",
            CameraMetadata.CONTROL_AWB_MODE_DAYLIGHT to "daylight",
            CameraMetadata.CONTROL_AWB_MODE_CLOUDY_DAYLIGHT to "cloudy",
            CameraMetadata.CONTROL_AWB_MODE_FLUORESCENT to "fluorescent",
            CameraMetadata.CONTROL_AWB_MODE_INCANDESCENT to "incandescent",
            CameraMetadata.CONTROL_AWB_MODE_WARM_FLUORESCENT to "warm",
            CameraMetadata.CONTROL_AWB_MODE_SHADE to "shade",
            CameraMetadata.CONTROL_AWB_MODE_TWILIGHT to "twilight",
        )

        fun awbFromName(name: String): Int =
            AWB_NAMES.entries.firstOrNull { it.value == name }?.key ?: CameraMetadata.CONTROL_AWB_MODE_AUTO

        fun loadAll(context: Context): List<CameraCaps> {
            val manager = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
            val encoderCaps = MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos
                .firstOrNull { it.isEncoder && it.supportedTypes.any { t -> t.equals(MediaFormat.MIMETYPE_VIDEO_AVC, true) } }
                ?.getCapabilitiesForType(MediaFormat.MIMETYPE_VIDEO_AVC)?.videoCapabilities

            val result = mutableListOf<CameraCaps>()
            val counters = mutableMapOf<String, Int>()
            for (id in manager.cameraIdList) {
                val ch = manager.getCameraCharacteristics(id)
                val caps = ch.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES) ?: intArrayOf()
                if (CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_BACKWARD_COMPATIBLE !in caps) continue

                val facing = when (ch.get(CameraCharacteristics.LENS_FACING)) {
                    CameraMetadata.LENS_FACING_FRONT -> "front"
                    CameraMetadata.LENS_FACING_BACK -> "back"
                    else -> "external"
                }
                val n = (counters[facing] ?: 0) + 1
                counters[facing] = n
                val baseLabel = when (facing) {
                    "front" -> "Frontal"
                    "back" -> "Traseira"
                    else -> "Externa"
                }
                val label = if (n == 1) baseLabel else "$baseLabel $n"

                val map = ch.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ?: continue
                val sizes = (map.getOutputSizes(MediaCodec::class.java) ?: emptyArray())
                    .filter { it.width >= 320 && it.width <= 3840 && it.height <= 2160 }
                    .filter { encoderCaps == null || encoderCaps.isSizeSupported(it.width, it.height) }
                    .map { size ->
                        val minDur = map.getOutputMinFrameDuration(MediaCodec::class.java, size)
                        var maxFps = if (minDur > 0) (1_000_000_000.0 / minDur).toInt() else 30
                        if (encoderCaps != null) {
                            runCatching {
                                maxFps = minOf(maxFps, encoderCaps.getSupportedFrameRatesFor(size.width, size.height).upper.toInt())
                            }
                        }
                        intArrayOf(size.width, size.height, maxFps)
                    }
                    .distinctBy { it[0] * 100000 + it[1] }
                    .sortedByDescending { it[0] * it[1] }
                if (sizes.isEmpty()) continue

                val fpsRanges = (ch.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES) ?: emptyArray())
                    .map { intArrayOf(it.lower, it.upper) }

                var zoomMin = 1f
                var zoomMax = ch.get(CameraCharacteristics.SCALER_AVAILABLE_MAX_DIGITAL_ZOOM) ?: 1f
                var byRatio = false
                if (Build.VERSION.SDK_INT >= 30) {
                    ch.get(CameraCharacteristics.CONTROL_ZOOM_RATIO_RANGE)?.let {
                        zoomMin = it.lower
                        zoomMax = it.upper
                        byRatio = true
                    }
                }

                val evRange = ch.get(CameraCharacteristics.CONTROL_AE_COMPENSATION_RANGE)
                val evStep = ch.get(CameraCharacteristics.CONTROL_AE_COMPENSATION_STEP)
                val iso = ch.get(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE)
                val exp = ch.get(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE)
                val awbAvail = (ch.get(CameraCharacteristics.CONTROL_AWB_AVAILABLE_MODES) ?: intArrayOf()).toSet()
                val stabModes = ch.get(CameraCharacteristics.CONTROL_AVAILABLE_VIDEO_STABILIZATION_MODES) ?: intArrayOf()
                val aeModes = ch.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_MODES) ?: intArrayOf()

                result += CameraCaps(
                    id = id,
                    facing = facing,
                    label = label,
                    sensorOrientation = ch.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 90,
                    sizes = sizes,
                    fpsRanges = fpsRanges,
                    zoomMin = zoomMin,
                    zoomMax = zoomMax,
                    zoomByRatio = byRatio,
                    evMin = evRange?.lower ?: 0,
                    evMax = evRange?.upper ?: 0,
                    evStep = evStep?.toFloat() ?: 1f,
                    hasFlash = ch.get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true,
                    manualSensor = CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR in caps && iso != null && exp != null,
                    isoMin = iso?.lower ?: 100,
                    isoMax = iso?.upper ?: 100,
                    expMinNs = exp?.lower ?: 1_000_000L,
                    expMaxNs = exp?.upper ?: 100_000_000L,
                    minFocusDist = ch.get(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE) ?: 0f,
                    afModes = (ch.get(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES) ?: intArrayOf()).toSet(),
                    awbModes = AWB_NAMES.filterKeys { it in awbAvail }.values.toList(),
                    stabilization = CameraMetadata.CONTROL_VIDEO_STABILIZATION_MODE_ON in stabModes,
                    lowLightBoost = AE_MODE_LOW_LIGHT_BOOST in aeModes,
                )
            }
            return result
        }
    }
}
