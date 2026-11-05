plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.1.0" apply false
}

// A pasta de build fica fora do vault (pesa centenas de MB e nao precisa sincronizar).
val buildRoot = System.getenv("LOCALAPPDATA")?.let { File(it, "celular-webcam-build") }
if (buildRoot != null) {
    allprojects {
        layout.buildDirectory.set(File(buildRoot, project.name))
    }
}
