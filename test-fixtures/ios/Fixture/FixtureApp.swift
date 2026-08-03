import SwiftUI

@main
struct FixtureApp: App {
    var body: some Scene {
        WindowGroup {
            Text("ci-workflows fixture")
        }
    }
}

// Something for the unit test to assert on.
enum Calc {
    static func add(_ a: Int, _ b: Int) -> Int { a + b }
}
