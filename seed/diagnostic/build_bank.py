"""Builds seed/diagnostic/grade_XX.json, the sign-up check-in bank.

Two multiple-choice items per CAPS topic: "core" is asked first; "easier"
is asked only when the core item is missed, so one slip doesn't mark a
whole topic weak. Wrong options name the misconception they catch (codes
from the misconceptions table). `check` is a SymPy expression for the
correct option's value where the answer is computable; the unit tests
evaluate it and confirm exactly one option matches.

STATUS: written 5 Nov 2026 for the pilot, NOT yet reviewed by a maths
teacher. Review every item before learners see it (founder decision).

Run: python -m seed.diagnostic.build_bank
"""

import json
from pathlib import Path

HERE = Path(__file__).parent


def item(stem, options, answer, misc=None, check=None):
    assert answer in "ABCD"[:len(options)]
    return {"stem": stem, "options": options, "answer": answer, "misc": misc or {},
            "check": check}


BANK: dict[int, dict[str, tuple[dict, dict]]] = {
    8: {
        "Whole numbers": (
            item("What is the HCF (highest common factor) of 24 and 36?",
                 ["6", "12", "72", "4"], "B", {"A": "MISREAD", "C": "MISREAD", "D": "MISREAD"},
                 "gcd(24, 36)"),
            item("Round 4 768 to the nearest hundred.",
                 ["4 700", "4 800", "5 000", "4 770"], "B",
                 {"A": "PLACE_VALUE", "C": "PLACE_VALUE", "D": "PLACE_VALUE"}, "4800")),
        "Integers": (
            item("What is -12 ÷ (-3) + (-5)?", ["-9", "-1", "9", "1"], "B",
                 {"A": "SIGN_ERR", "C": "SIGN_ERR", "D": "SIGN_ERR"}, "-12/(-3) + (-5)"),
            item("What is -8 + 3?", ["11", "-11", "-5", "5"], "C",
                 {"A": "SIGN_ERR", "B": "SIGN_ERR", "D": "SIGN_ERR"}, "-8 + 3")),
        "Exponents": (
            item("Simplify 2^3 × 2^4", ["2^7", "2^12", "4^7", "2^1"], "A",
                 {"B": "EXP_AS_MULT", "C": "EXP_AS_MULT", "D": "SIGN_ERR"}, "2**7"),
            item("What is 3^2?", ["6", "9", "5", "32"], "B",
                 {"A": "EXP_AS_MULT", "C": "MISREAD", "D": "MISREAD"}, "3**2")),
        "Numeric and Geometric Patterns": (
            item("The pattern is 5; 9; 13; 17; ... What is the 10th term?",
                 ["41", "45", "37", "21"], "A", {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"},
                 "4*10 + 1"),
            item("What is the next number: 3; 6; 12; 24; ...?", ["30", "48", "36", "27"], "B",
                 {"A": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "48")),
        "Functions and Relationships": (
            item("If y = 3x - 2, what is y when x = -4?", ["-14", "10", "-10", "14"], "A",
                 {"B": "SIGN_ERR", "C": "SIGN_ERR", "D": "SIGN_ERR"}, "3*(-4) - 2"),
            item("The rule is 'multiply by 2, then add 1'. What comes out when 5 goes in?",
                 ["11", "12", "7", "10"], "A", {"B": "ORDER_OPS", "C": "MISREAD", "D": "MISREAD"},
                 "5*2 + 1")),
        "Algebraic Expressions": (
            item("Simplify 3a + 2b + 5a - b", ["8a + b", "8a + 3b", "9ab", "8a - b"], "A",
                 {"B": "SIGN_ERR", "C": "UNLIKE_TERMS", "D": "SIGN_ERR"}),
            item("Expand 2(x + 5)", ["2x + 5", "2x + 10", "x + 10", "2x + 7"], "B",
                 {"A": "PARTIAL_DISTRIB", "C": "PARTIAL_DISTRIB", "D": "MISREAD"})),
        "Algebraic Equations": (
            item("Solve 3x + 4 = 19", ["x = 5", "x = 23/3", "x = 15", "x = 7"], "A",
                 {"B": "ONE_SIDE_OP", "C": "MISREAD", "D": "MISREAD"}, "5"),
            item("Solve x - 7 = 2", ["x = 9", "x = -5", "x = 5", "x = 14"], "A",
                 {"B": "SIGN_ERR", "C": "ONE_SIDE_OP", "D": "MISREAD"}, "9")),
        "Construction of Geometric Figures": (
            item("You bisect an angle of 70° with a compass. What is the size of each new angle?",
                 ["35°", "140°", "70°", "20°"], "A", {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"},
                 "70/2"),
            item("Which instrument do you use to draw a circle with a radius of 4 cm?",
                 ["Protractor", "Compass", "Set square", "Calculator"], "B")),
        "Geometry of 2D Shapes": (
            item("Two angles of a triangle are 50° and 60°. What is the third angle?",
                 ["70°", "110°", "80°", "90°"], "A", {"B": "MISREAD"}, "180 - 50 - 60"),
            item("A quadrilateral with all sides equal and all angles 90° is a ...",
                 ["Rhombus", "Square", "Kite", "Trapezium"], "B")),
        "Geometry of Straight Lines": (
            item("Two angles lie next to each other on a straight line. One is 125°. What is the other?",
                 ["55°", "65°", "235°", "125°"], "A", {"C": "MISREAD", "D": "MISREAD"}, "180 - 125"),
            item("Vertically opposite angles are ...",
                 ["Equal", "Add up to 90°", "Add up to 180°", "Add up to 360°"], "A")),
        "Common Fractions": (
            item("Calculate 1/3 + 1/6", ["2/9", "1/2", "2/6", "1/9"], "B",
                 {"A": "FRAC_ADD_ACROSS", "C": "FRAC_ADD_ACROSS", "D": "MISREAD"},
                 "Rational(1, 3) + Rational(1, 6)"),
            item("Which fraction is equal to 3/4?", ["6/8", "4/3", "3/8", "7/8"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "Rational(3, 4)")),
        "Decimal Fractions": (
            item("Calculate 0.4 × 0.3", ["1.2", "0.12", "0.012", "0.7"], "B",
                 {"A": "PLACE_VALUE", "C": "PLACE_VALUE", "D": "MISREAD"}, "Rational(12, 100)"),
            item("Which number is the biggest?", ["0.5", "0.45", "0.405", "0.054"], "A",
                 {"B": "PLACE_VALUE", "C": "PLACE_VALUE", "D": "PLACE_VALUE"}, "Rational(1, 2)")),
        "Theorem of Pythagoras": (
            item("A right-angled triangle has shorter sides of 6 cm and 8 cm. How long is the longest side?",
                 ["10 cm", "14 cm", "100 cm", "48 cm"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "sqrt(6**2 + 8**2)"),
            item("In a right-angled triangle, the longest side is called the ...",
                 ["Hypotenuse", "Base", "Height", "Diagonal"], "A")),
        "Area and Perimeter": (
            item("A rectangle is 7 cm long and 4 cm wide. What is its area?",
                 ["28 cm²", "22 cm²", "11 cm²", "28 cm"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "UNITS"}, "7*4"),
            item("What is the perimeter of a square with sides of 5 cm?",
                 ["20 cm", "25 cm", "10 cm", "25 cm²"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "4*5")),
        "Surface Area and Volume": (
            item("What is the volume of a box that is 5 cm by 3 cm by 2 cm?",
                 ["30 cm³", "10 cm³", "62 cm³", "30 cm²"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "UNITS"}, "5*3*2"),
            item("A cube has edges of 2 cm. What is its volume?", ["8 cm³", "6 cm³", "4 cm³", "24 cm³"],
                 "A", {"B": "EXP_AS_MULT", "C": "MISREAD", "D": "MISREAD"}, "2**3")),
        "Collect, Organize and Summarize Data": (
            item("Test marks: 3, 5, 5, 8, 9. What is the mean?", ["6", "5", "30", "8.5"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "(3 + 5 + 5 + 8 + 9)/5"),
            item("Data: 2, 5, 5, 6, 9. What is the mode?", ["5", "6", "9", "7"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "5")),
        "Represent Data": (
            item("A pie chart shows that 25% of learners walk to school. What is the angle of that slice?",
                 ["90°", "25°", "45°", "180°"], "A", {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"},
                 "Rational(25, 100)*360"),
            item("Which graph is best for showing how the temperature changes during a day?",
                 ["Line graph", "Pie chart", "Pictograph", "Stem-and-leaf plot"], "A")),
        "Interpret, Analyse and Report Data": (
            item("The test scores in a class go from 35 to 92. What is the range?",
                 ["57", "127", "63.5", "92"], "A", {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"},
                 "92 - 35"),
            item("A survey about learners' favourite sport asked only the netball team. What is the problem?",
                 ["The sample is biased", "The sample is too big", "There are too many questions",
                  "Nothing is wrong"], "A")),
        "Graphs": (
            item("A distance-time graph is a straight line from (0; 0) to (4; 200), time in hours and "
                 "distance in km. What is the speed?", ["50 km/h", "200 km/h", "4 km/h", "800 km/h"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "200/4"),
            item("On a distance-time graph, a flat (horizontal) part means the object is ...",
                 ["Standing still", "Speeding up", "Slowing down", "Going backwards"], "A")),
        "Transformation Geometry": (
            item("The point (3; -2) is reflected in the y-axis. Where does it land?",
                 ["(-3; -2)", "(3; 2)", "(-3; 2)", "(-2; 3)"], "A",
                 {"B": "MISREAD", "C": "SIGN_ERR", "D": "MISREAD"}),
            item("The point (1; 4) moves 3 units to the right. Where does it land?",
                 ["(4; 4)", "(1; 7)", "(-2; 4)", "(4; 7)"], "A",
                 {"B": "MISREAD", "C": "SIGN_ERR", "D": "MISREAD"})),
        "Geometry of 3D Objects": (
            item("How many faces does a triangular prism have?", ["5", "6", "9", "3"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "5"),
            item("How many edges does a cube have?", ["12", "6", "8", "24"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "12")),
        "Probability": (
            item("A bag has 3 red and 5 blue sweets. You take one without looking. What is the "
                 "probability that it is red?", ["3/8", "3/5", "5/8", "1/3"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "Rational(3, 8)"),
            item("A fair coin is tossed once. What is the probability of heads?", ["1/2", "1", "0", "2"],
                 "A", {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "Rational(1, 2)")),
    },
    10: {
        "Algebraic expressions": (
            item("Factorise x^2 + 5x + 6", ["(x + 2)(x + 3)", "(x + 1)(x + 6)", "(x - 2)(x - 3)",
                                           "x(x + 5) + 6"], "A",
                 {"B": "MISREAD", "C": "SIGN_ERR", "D": "MISREAD"}),
            item("Expand (x + 3)(x - 2)", ["x^2 + x - 6", "x^2 - 6", "x^2 + 5x - 6", "x^2 - x - 6"], "A",
                 {"B": "PARTIAL_DISTRIB", "C": "SIGN_ERR", "D": "SIGN_ERR"})),
        "Equations and inequalities": (
            item("Solve x^2 - 5x + 6 = 0", ["x = 2 or x = 3", "x = -2 or x = -3", "x = 6 or x = 1",
                                           "x = 5"], "A", {"B": "SIGN_ERR", "C": "MISREAD", "D": "MISREAD"}),
            item("Solve 2x - 3 > 7", ["x > 5", "x > 2", "x < 5", "x > 10"], "A",
                 {"B": "SIGN_ERR", "C": "MISREAD", "D": "ONE_SIDE_OP"})),
        "Exponents": (
            item("Simplify (2x^3)^2", ["4x^6", "2x^6", "4x^5", "2x^9"], "A",
                 {"B": "PARTIAL_DISTRIB", "C": "EXP_AS_MULT", "D": "EXP_AS_MULT"}),
            item("Calculate 5^0 + 2^(-1)", ["3/2", "1/2", "5/2", "-2"], "A",
                 {"B": "EXP_AS_MULT", "C": "EXP_AS_MULT", "D": "SIGN_ERR"}, "5**0 + Rational(1, 2)")),
        "Number patterns": (
            item("What is the general term of 7; 11; 15; 19; ...?",
                 ["Tn = 4n + 3", "Tn = 4n + 7", "Tn = 7n + 4", "Tn = n + 4"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}),
            item("What is the next term: 2; 5; 8; 11; ...?", ["14", "13", "15", "22"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "14")),
        "Trigonometry": (
            item("In triangle ABC, angle B = 90°, AB = 3, BC = 4 and AC = 5. What is sin A?",
                 ["4/5", "3/5", "3/4", "4/3"], "A", {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"},
                 "Rational(4, 5)"),
            item("What is sin 30°?", ["1/2", "√3/2", "1", "30"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "Rational(1, 2)")),
        "Functions": (
            item("Where does the graph of y = 2x^2 - 8 cut the x-axis?",
                 ["x = -2 and x = 2", "x = -8", "x = -4 and x = 4", "x = 8"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}),
            item("What is the y-intercept of y = 3x - 6?", ["-6", "3", "2", "6"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "SIGN_ERR"}, "-6")),
        "Trigonometric functions": (
            item("What is the maximum value of y = 2 sin x + 1?", ["3", "2", "1", "4"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "2 + 1"),
            item("What is the period of y = cos x?", ["360°", "180°", "90°", "720°"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "360")),
        "Euclidean Geometry": (
            item("In parallelogram ABCD, angle A = 110°. What is angle B?", ["70°", "110°", "250°", "55°"],
                 "A", {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "180 - 110"),
            item("The diagonals of a rectangle are always ...",
                 ["Equal in length", "Perpendicular", "Parallel", "Equal to the sides"], "A")),
        "Analytical Geometry": (
            item("What is the distance between A(1; 2) and B(4; 6)?", ["5", "7", "25", "√7"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "sqrt((4 - 1)**2 + (6 - 2)**2)"),
            item("What is the midpoint of (2; 4) and (6; 8)?", ["(4; 6)", "(8; 12)", "(2; 2)", "(3; 4)"],
                 "A", {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"})),
        "Finance and growth": (
            item("R1 000 is invested at 10% per year compound interest for 2 years. What is it worth?",
                 ["R1 210", "R1 200", "R1 100", "R1 020"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "PLACE_VALUE"}, "1000*Rational(11, 10)**2"),
            item("R500 earns 8% per year simple interest for 3 years. How much interest is that?",
                 ["R120", "R40", "R620", "R1 200"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "PLACE_VALUE"}, "500*Rational(8, 100)*3")),
        "Measurement": (
            item("What is the volume of a cylinder with radius 3 cm and height 10 cm? Use π ≈ 3.14.",
                 ["282.6 cm³", "94.2 cm³", "188.4 cm³", "28.26 cm³"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "PLACE_VALUE"}, "Rational(314, 100)*3**2*10"),
            item("What is the area of a circle with radius 2 m? Use π ≈ 3.14.",
                 ["12.56 m²", "6.28 m²", "12.56 m", "4 m²"], "A",
                 {"B": "MISREAD", "C": "UNITS", "D": "MISREAD"}, "Rational(314, 100)*2**2")),
        "Statistics": (
            item("What is the median of 3; 8; 5; 12; 7; 10?", ["7.5", "5", "8.5", "9"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "Rational(7 + 8, 2)"),
            item("What is the range of 4; 9; 2; 15; 7?", ["13", "15", "11", "7.4"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "15 - 2")),
        "Probability": (
            item("A and B are mutually exclusive, P(A) = 0.3 and P(B) = 0.5. What is P(A or B)?",
                 ["0.8", "0.15", "0.65", "0.2"], "A", {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"},
                 "Rational(3, 10) + Rational(5, 10)"),
            item("A fair dice is rolled once. What is the probability of an even number?",
                 ["1/2", "1/3", "1/6", "2/3"], "A", {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"},
                 "Rational(3, 6)")),
    },
    11: {
        "Exponents and surds": (
            item("Simplify √50 - √8", ["3√2", "√42", "7√2", "3"], "A",
                 {"B": "UNLIKE_TERMS", "C": "SIGN_ERR", "D": "MISREAD"}, "sqrt(50) - sqrt(8)"),
            item("Solve 2^x = 16", ["x = 4", "x = 8", "x = 2", "x = 32"], "A",
                 {"B": "EXP_AS_MULT", "C": "MISREAD", "D": "MISREAD"}, "4")),
        "Equations and inequalities": (
            item("Solve x^2 - 4x - 1 = 0 with the quadratic formula.",
                 ["x = 2 ± √5", "x = -2 ± √5", "x = 4 ± √5", "x = 2 ± √3"], "A",
                 {"B": "SIGN_ERR", "C": "MISREAD", "D": "MISREAD"}),
            item("Solve x^2 - 9 < 0", ["-3 < x < 3", "x < 3", "x < -3 or x > 3", "x < 9"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"})),
        "Number patterns": (
            item("What is the general term of 2; 5; 10; 17; ...?",
                 ["Tn = n^2 + 1", "Tn = 3n - 1", "Tn = 2n^2", "Tn = n^2 + 2"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}),
            item("The first differences of a pattern are 3; 5; 7; 9. What is the second difference?",
                 ["2", "3", "0", "9"], "A", {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "2")),
        "Analytical Geometry": (
            item("What is the gradient of a line perpendicular to y = 2x + 1?", ["-1/2", "2", "-2", "1/2"],
                 "A", {"B": "MISREAD", "C": "MISREAD", "D": "SIGN_ERR"}, "Rational(-1, 2)"),
            item("A line has gradient 2 and passes through (0; 3). What is its equation?",
                 ["y = 2x + 3", "y = 3x + 2", "y = 2x - 3", "y = x + 3"], "A",
                 {"B": "MISREAD", "C": "SIGN_ERR", "D": "MISREAD"})),
        "Functions": (
            item("What is the turning point of y = (x - 2)^2 + 3?", ["(2; 3)", "(-2; 3)", "(2; -3)", "(3; 2)"],
                 "A", {"B": "SIGN_ERR", "C": "SIGN_ERR", "D": "MISREAD"}),
            item("What are the asymptotes of y = 1/(x - 1) + 2?",
                 ["x = 1 and y = 2", "x = -1 and y = 2", "x = 2 and y = 1", "x = 0 and y = 0"], "A",
                 {"B": "SIGN_ERR", "C": "MISREAD", "D": "MISREAD"})),
        "Trigonometry (reduction formulae, graphs, equations)": (
            item("Simplify sin(180° - θ)", ["sin θ", "-sin θ", "cos θ", "-cos θ"], "A",
                 {"B": "SIGN_ERR", "C": "MISREAD", "D": "MISREAD"}),
            item("cos(360° - θ) = ?", ["cos θ", "-cos θ", "sin θ", "-sin θ"], "A",
                 {"B": "SIGN_ERR", "C": "MISREAD", "D": "MISREAD"})),
        "Measurement": (
            item("What is the volume of a sphere with radius 3 cm? V = 4/3 π r^3, use π ≈ 3.14.",
                 ["113.04 cm³", "37.68 cm³", "28.26 cm³", "339.12 cm³"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "Rational(4, 3)*Rational(314, 100)*27"),
            item("What is the total surface area of a cube with edges of 3 cm?",
                 ["54 cm²", "27 cm²", "9 cm²", "36 cm²"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "6*3**2")),
        "Euclidean Geometry": (
            item("An angle at the centre of a circle is 100°. What is the angle at the circumference "
                 "on the same arc?", ["50°", "100°", "200°", "80°"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "100/2"),
            item("The angle in a semicircle is ...", ["90°", "180°", "60°", "45°"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "90")),
        "Trigonometry (sine, area, cosine rules)": (
            item("A triangle has sides 6 cm and 8 cm with an included angle of 30°. What is its area?",
                 ["12 cm²", "24 cm²", "48 cm²", "20.8 cm²"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "Rational(1, 2)*6*8*Rational(1, 2)"),
            item("You know two sides and the angle between them and need the third side. Which rule?",
                 ["Cosine rule", "Sine rule", "Area rule", "Theorem of Pythagoras"], "A")),
        "Probability": (
            item("A and B are independent, P(A) = 0.4 and P(B) = 0.5. What is P(A and B)?",
                 ["0.2", "0.9", "0.1", "0.45"], "A", {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"},
                 "Rational(4, 10)*Rational(5, 10)"),
            item("If P(A) = 0.35, what is P(not A)?", ["0.65", "0.35", "1.35", "0"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "1 - Rational(35, 100)")),
        "Finance, growth and decay": (
            item("A car worth R200 000 loses value at 10% per year on the reducing balance. "
                 "What is it worth after 2 years?", ["R162 000", "R160 000", "R180 000", "R242 000"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "SIGN_ERR"}, "200000*Rational(9, 10)**2"),
            item("Interest is 12% per year, compounded monthly. What is the interest rate per month?",
                 ["1%", "12%", "0.12%", "144%"], "A", {"B": "MISREAD", "C": "PLACE_VALUE", "D": "MISREAD"},
                 "12/12")),
        "Statistics": (
            item("A data set has Q1 = 20 and Q3 = 35. What is the interquartile range?",
                 ["15", "55", "27.5", "35"], "A", {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"},
                 "35 - 20"),
            item("In a box-and-whisker plot, the line inside the box shows the ...",
                 ["Median", "Mean", "Mode", "Range"], "A")),
    },
    12: {
        "Patterns, sequences and series": (
            item("What is the sum to infinity of 16 + 8 + 4 + ...?", ["32", "28", "64", "16"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "16/(1 - Rational(1, 2))"),
            item("In the arithmetic sequence 3; 7; 11; ..., what is T20?", ["79", "83", "80", "76"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "3 + 19*4")),
        "Functions and inverse functions": (
            item("What is the inverse of f(x) = 2x + 4?",
                 ["f⁻¹(x) = (x - 4)/2", "f⁻¹(x) = 2x - 4", "f⁻¹(x) = x/2 + 4", "f⁻¹(x) = 1/(2x + 4)"], "A",
                 {"B": "MISREAD", "C": "ORDER_OPS", "D": "MISREAD"}),
            item("The graph of an inverse function is the reflection of the graph in the line ...",
                 ["y = x", "y = 0", "x = 0", "y = -x"], "A")),
        "Exponential and logarithmic functions": (
            item("Solve log2(x) = 5", ["x = 32", "x = 10", "x = 25", "x = 2.5"], "A",
                 {"B": "EXP_AS_MULT", "C": "MISREAD", "D": "MISREAD"}, "2**5"),
            item("What is the inverse of y = 3^x?", ["y = log3(x)", "y = x^3", "y = 3^(-x)", "y = 1/3^x"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"})),
        "Finance, growth and decay": (
            item("What is the effective annual rate of 12% per year compounded monthly, to two decimals?",
                 ["12.68%", "12.00%", "1.00%", "13.00%"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "Rational(1268, 100)"),
            item("Which formula gives the future value of equal monthly payments into savings?",
                 ["F = x[(1 + i)^n - 1]/i", "A = P(1 + i)^n", "A = P(1 + in)", "P = x[1 - (1 + i)^(-n)]/i"],
                 "A", {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"})),
        "Trigonometry - compound angles": (
            item("cos(A - B) = ?", ["cos A cos B + sin A sin B", "cos A cos B - sin A sin B",
                                    "sin A cos B - cos A sin B", "cos A - cos B"], "A",
                 {"B": "SIGN_ERR", "C": "MISREAD", "D": "PARTIAL_DISTRIB"}),
            item("sin 2x = ?", ["2 sin x cos x", "2 sin x", "sin^2 x - cos^2 x", "sin x + sin x"], "A",
                 {"B": "PARTIAL_DISTRIB", "C": "MISREAD", "D": "PARTIAL_DISTRIB"})),
        "Trigonometry 2D and 3D": (
            item("From the top of a 20 m building, the angle of depression to a car is 30°. How far is "
                 "the car from the foot of the building?", ["34.6 m", "11.5 m", "40 m", "17.3 m"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "Rational(346, 10)"),
            item("The angle of elevation from A to B equals the angle of depression from B to A because "
                 "they are ...", ["Alternate angles", "Co-interior angles", "Vertically opposite angles",
                                  "Supplementary angles"], "A")),
        "Polynomial functions": (
            item("f(x) = x^3 - 2x^2 - 5x + 6. Is (x - 1) a factor of f(x)?",
                 ["Yes, because f(1) = 0", "No, because f(-1) ≠ 0", "Yes, because f(-1) = 0",
                  "No, because f(1) = 6"], "A", {"B": "SIGN_ERR", "C": "SIGN_ERR", "D": "MISREAD"}),
            item("What is the remainder when x^2 + 3x - 4 is divided by (x - 2)?", ["6", "0", "-6", "2"],
                 "A", {"B": "MISREAD", "C": "SIGN_ERR", "D": "MISREAD"}, "2**2 + 3*2 - 4")),
        "Differential calculus": (
            item("If f(x) = x^3 - 6x, what is f'(x)?", ["3x^2 - 6", "3x - 6", "3x^2 - 6x", "x^2 - 6"], "A",
                 {"B": "EXP_AS_MULT", "C": "MISREAD", "D": "MISREAD"}),
            item("What is the derivative of 5x^2?", ["10x", "5x", "10x^2", "2x"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"})),
        "Analytical Geometry": (
            item("What are the centre and radius of (x - 2)^2 + (y + 3)^2 = 16?",
                 ["(2; -3) and r = 4", "(-2; 3) and r = 4", "(2; -3) and r = 16", "(2; 3) and r = 4"], "A",
                 {"B": "SIGN_ERR", "C": "MISREAD", "D": "SIGN_ERR"}),
            item("A tangent to a circle is ... to the radius at the point of contact.",
                 ["Perpendicular", "Parallel", "Equal", "Half"], "A")),
        "Euclidean Geometry": (
            item("In triangle ABC, DE ∥ BC with D on AB and E on AC. AD = 4, DB = 6 and AE = 6. "
                 "What is EC?", ["9", "4", "6", "10"], "A",
                 {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "6*6/4"),
            item("Two triangles are similar when their angles are equal and their sides are ...",
                 ["In proportion", "Equal", "Parallel", "Perpendicular"], "A")),
        "Statistics (regression and correlation)": (
            item("A correlation coefficient of r = -0.92 shows ...",
                 ["A strong negative correlation", "A weak negative correlation",
                  "A strong positive correlation", "No correlation"], "A",
                 {"B": "MISREAD", "C": "SIGN_ERR", "D": "MISREAD"}),
            item("In the least squares line y = a + bx, what is b?",
                 ["The gradient", "The y-intercept", "The correlation coefficient", "The mean"], "A")),
        "Counting and Probability": (
            item("How many different arrangements of the letters of the word MATHS are there?",
                 ["120", "25", "5", "60"], "A", {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"},
                 "factorial(5)"),
            item("How many outfits can you make from 3 shirts and 4 pairs of pants?", ["12", "7", "34", "81"],
                 "A", {"B": "MISREAD", "C": "MISREAD", "D": "MISREAD"}, "3*4")),
    },
}


def build() -> dict[int, list[dict]]:
    out = {}
    for grade, topics in BANK.items():
        items = []
        for topic, (core, easier) in topics.items():
            slug = "".join(ch for ch in topic.lower() if ch.isalnum())[:18]
            for kind, it in (("core", core), ("easier", easier)):
                items.append({"id": f"G{grade:02d}-{slug}-{kind}", "grade": grade, "topic": topic,
                              "kind": kind, **it})
        out[grade] = items
    return out


def main() -> None:
    for grade, items in build().items():
        path = HERE / f"grade_{grade:02d}.json"
        path.write_text(json.dumps({"version": "2026-11-05", "reviewed": False, "items": items},
                                   ensure_ascii=False, indent=1) + "\n")
        print(f"Grade {grade}: {len(items)} items -> {path.name}")


if __name__ == "__main__":
    main()
