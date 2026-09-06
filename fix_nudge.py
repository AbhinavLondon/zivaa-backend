file_path = '../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/presentation/dashboard/DashboardScreen.kt'
with open(file_path, 'r', encoding='utf-8') as f:
    text = f.read()

# Replace font size
target1 = """              // Title
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

replacement1 = """              // Title
              Text(
                  text = alert.nudge_title ?: "Recent Anomaly Detected",
                  style = ZivaaTheme.typography.cardTitle.copy(
                      fontStyle = FontStyle.Normal,
                      fontSize = 20.sp,
                      lineHeight = (20 * 1.14).sp,
                      letterSpacing = (-0.01).em
                  ),
                  color = inkDark
              )"""

text = text.replace(target1, replacement1)

# Remove spacer
target2 = """                        }
                    }
            }
            Spacer(modifier = Modifier.height(110.dp))
        }
    }
}"""
# Wait, let's just do a simpler replace for the spacer because indentation might be tricky
text = text.replace('Spacer(modifier = Modifier.height(110.dp))', '')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(text)
