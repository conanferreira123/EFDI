$src = "C:\Users\conanferreira\Desktop\PROJECT-BLACKBOX\EFDI\backend\pgvector_dist"
$dst = "C:\Program Files\PostgreSQL\18"

Write-Host "Copying pgvector files from $src to $dst..."
Copy-Item -Path "$src\lib\*" -Destination "$dst\lib" -Force -Recurse
Copy-Item -Path "$src\share\extension\*" -Destination "$dst\share\extension" -Force -Recurse
if (Test-Path "$src\include") {
    Copy-Item -Path "$src\include\*" -Destination "$dst\include" -Force -Recurse
}
Write-Host "Done copying pgvector files!"
