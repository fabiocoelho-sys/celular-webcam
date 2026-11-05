import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// A chave de assinatura oficial fica fora do repositorio (keystore/ esta no .gitignore).
// Sem ela (quem clonar do GitHub), o app e assinado com a chave de debug padrao.
val keystoreProps = Properties().apply {
    val f = rootProject.file("keystore/keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "com.fabio.celularwebcam"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.fabio.celularwebcam"
        minSdk = 23 // Android 6: cobre aparelhos antigos como o Xperia XA (F3116)
        targetSdk = 35
        versionCode = 4
        versionName = "1.2.0"
    }

    signingConfigs {
        if (keystoreProps.isNotEmpty()) {
            create("projeto") {
                storeFile = rootProject.file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        val assinatura = signingConfigs.findByName("projeto") ?: signingConfigs.getByName("debug")
        getByName("debug") {
            signingConfig = assinatura
        }
        getByName("release") {
            isMinifyEnabled = false
            signingConfig = assinatura
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}
