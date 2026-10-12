plugins { id("com.android.application"); id("org.jetbrains.kotlin.android"); id("org.jetbrains.kotlin.plugin.compose"); id("org.jetbrains.kotlin.kapt") }
android {
    namespace = "site.leospace.qdrop"
    compileSdk = 36
    buildToolsVersion = "36.0.0"
    defaultConfig { applicationId = "site.leospace.qdrop"; minSdk = 29; targetSdk = 36; versionCode = 1; versionName = "0.1.0"; testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner" }
    buildFeatures { compose = true; buildConfig = true }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    val keyPath = System.getenv("QDROP_KEYSTORE")
    if (keyPath != null) signingConfigs.create("privateRelease") { storeFile = file(keyPath); storePassword = System.getenv("QDROP_STORE_PASSWORD"); keyAlias = System.getenv("QDROP_KEY_ALIAS"); keyPassword = System.getenv("QDROP_KEY_PASSWORD") }
    buildTypes {
        debug { applicationIdSuffix = ".debug"; versionNameSuffix = "-debug"; resValue("string", "app_name", "QDrop Debug") }
        release { isMinifyEnabled = false; if (keyPath != null) signingConfig = signingConfigs.getByName("privateRelease"); resValue("string", "app_name", "QDrop") }
    }
    sourceSets["main"].assets.srcDir("../../protocol/fixtures")
}
dependencyLocking { lockAllConfigurations() }
dependencies {
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation(platform("androidx.compose:compose-bom:2025.04.01"))
    implementation("androidx.compose.material3:material3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.9.0")
    implementation("androidx.room:room-runtime:2.7.1")
    implementation("androidx.room:room-ktx:2.7.1")
    kapt("androidx.room:room-compiler:2.7.1")
    implementation("androidx.work:work-runtime-ktx:2.10.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
}
