file_path = '../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/presentation/dashboard/DashboardScreen.kt'
with open(file_path, 'r', encoding='utf-8') as f:
    text = f.read()

target = """              // Title
              Text(
                  text = alert.nudge_title ?: "Recent Anomaly Detected",
                  style = ZivaaTheme.typography.cardTitle.copy(
                      fontStyle = FontStyle.Normal,
                      fontSize = 23.sp,
                      lineHeight = (23 * 1.14).sp,
                      letterSpacing = (-0.01).em
                  ),
                  color = inkDark
              )"""

replacement = """              // Title
              Text(
                  text = alert.nudge_title ?: "Recent Anomaly Detected",
                  style = ZivaaTheme.typography.cardTitle.copy(
                      fontStyle = FontStyle.Normal,
                      fontSize = 18.sp,
                      lineHeight = (18 * 1.14).sp,
                      letterSpacing = (-0.01).em
                  ),
                  color = inkDark
              )"""

if target in text:
    text = text.replace(target, replacement)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Replaced successfully!")
else:
    print("Target not found! Attempting fallback replace.")
    text = text.replace('fontSize = 23.sp', 'fontSize = 18.sp')
    text = text.replace('lineHeight = (23 * 1.14).sp', 'lineHeight = (18 * 1.14).sp')
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(text)
