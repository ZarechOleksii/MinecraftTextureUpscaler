# Security policy

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private reporting instead: on the repository's
**Security** tab choose **Report a vulnerability**. Describe what you found and how to reproduce it; you will get an
answer as soon as the maintainer can, usually within a few days.

## Scope

regen4x reads PNG images, mod jars and resource-pack zip files that you give it and writes new files. Reports about
how it handles hostile input are in scope, for example a crafted zip that writes outside the output folder, a decompression
bomb, or a crash on a malformed image. Only the latest release is supported.
