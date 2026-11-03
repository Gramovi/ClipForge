# Extra CA certificates (optional)

Behind a TLS-intercepting corporate proxy, `pip`, `npm` and model downloads inside the Docker
build fail with "self-signed certificate in certificate chain". Put the proxy's root CA here as
`*.crt` (PEM) and rebuild – the images add it to their trust store. `*.crt` files are gitignored.
