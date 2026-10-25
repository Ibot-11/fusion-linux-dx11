# Building the reviewed Wine DLL

Install a MinGW-w64 cross compiler and run `make static` (or `make`). The result
is `dist/siappdll-static.dll`. MinHook's corresponding source is included under
`minhook/`, with its own license. This build uses the reviewed sibling
`siappdll/src` sources. See `../../README.md` for architecture and validation.

The DLL statically links its MinGW runtime and uses the Windows system socket
interface. The native relay is built separately from `../relay/main.c`.
