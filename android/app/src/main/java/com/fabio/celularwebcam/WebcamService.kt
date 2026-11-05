package com.fabio.celularwebcam

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log

/**
 * Servico em primeiro plano: e o que autoriza o Android a manter camera, microfone
 * e rede funcionando com a tela bloqueada. O trabalho em si fica no [WebcamEngine].
 */
class WebcamService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Mesmo para encerrar: quem usa startForegroundService precisa chamar startForeground
        runCatching { enterForeground() }.onFailure { Log.e(TAG, "startForeground", it) }
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        val engine = WebcamEngine.get(this)
        engine.onClientChanged = { refreshNotification() }
        engine.start()
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        // Parou por qualquer motivo: nada pode ficar ligado sem o servico autorizando
        WebcamEngine.peek()?.shutdown()
    }

    private fun enterForeground() {
        val notification = buildNotification()
        if (Build.VERSION.SDK_INT >= 30) {
            var type = ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
            }
            startForeground(NOTIFICATION_ID, notification, type)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun refreshNotification() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIFICATION_ID, buildNotification())
    }

    private fun buildNotification(): Notification {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        @Suppress("DEPRECATION")
        val builder = if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Webcam ativa", NotificationManager.IMPORTANCE_LOW),
            )
            Notification.Builder(this, CHANNEL_ID)
        } else {
            Notification.Builder(this)
        }

        val immutable = PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), immutable)
        val stop = PendingIntent.getService(
            this, 1, Intent(this, WebcamService::class.java).setAction(ACTION_STOP), immutable,
        )
        val text = when (val client = WebcamEngine.peek()?.server?.clientName) {
            null -> "Aguardando o PC"
            "127.0.0.1" -> "Conectado pelo cabo USB"
            else -> "Conectado ao PC $client"
        }
        @Suppress("DEPRECATION")
        return builder
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentTitle("Celular Webcam")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null, "Encerrar", stop).build())
            .build()
    }

    companion object {
        private const val TAG = "WebcamService"
        private const val CHANNEL_ID = "webcam"
        private const val NOTIFICATION_ID = 1
        private const val ACTION_STOP = "com.fabio.celularwebcam.STOP"

        /** Precisa ser chamado com a tela do app aberta: o Android exige isso para usar a camera. */
        fun start(context: Context) {
            val intent = Intent(context, WebcamService::class.java)
            runCatching {
                if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent) else context.startService(intent)
            }.onFailure { Log.e(TAG, "start", it) }
        }

        fun stop(context: Context) {
            runCatching {
                context.stopService(Intent(context, WebcamService::class.java))
            }.onFailure { Log.e(TAG, "stop", it) }
            WebcamEngine.peek()?.shutdown()
        }
    }
}
