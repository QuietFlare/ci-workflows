import XCTest
@testable import Fixture

final class FixtureTests: XCTestCase {
    func testAdditionWorks() {
        XCTAssertEqual(Calc.add(2, 2), 4)
    }
}
