// Deliberately the smallest possible Gradle project: plain Java + JUnit 4,
// no Kotlin plugin — the gradle-test workflow is language-agnostic (it just
// runs Gradle), and skipping the Kotlin toolchain keeps the smoke test fast.
plugins {
    java
}

repositories {
    mavenCentral()
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}
