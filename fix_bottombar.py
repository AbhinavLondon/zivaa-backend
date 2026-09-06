import re
with open('../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/presentation/MainActivity.kt', 'r', encoding='utf-8') as f:
    text = f.read()

target = """                                bottomBar = {
                                    androidx.compose.foundation.layout.Box("""

replacement = """                                bottomBar = {
                                    if (currentScreen != "coach_chat") {
                                    androidx.compose.foundation.layout.Box("""

text = text.replace(target, replacement)

target2 = """                                            }
                                        }
                                    }
                                },
                                floatingActionButton = {"""

replacement2 = """                                            }
                                        }
                                    }
                                    }
                                },
                                floatingActionButton = {"""

text = text.replace(target2, replacement2)

with open('../ZivaaSeniorApp/app/src/main/java/com/zivaa/app/presentation/MainActivity.kt', 'w', encoding='utf-8') as f:
    f.write(text)
