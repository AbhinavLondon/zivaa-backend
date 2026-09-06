$content = Get-Content -Path 'app/services/longevity_engine.py' -Raw
$content = $content.Replace('[
  {
', '[
  {{
')
$content = $content.Replace('[
  {
', '[
  {{
')
Set-Content -Path 'app/services/longevity_engine.py' -Value $content
