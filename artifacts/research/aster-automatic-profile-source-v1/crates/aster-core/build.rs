// When the `embed-net` feature is enabled, verify the pinned Aster core
// network before it is embedded into the binary.
fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    if std::env::var_os("CARGO_FEATURE_EMBED_NET").is_none() {
        return;
    }
    use sha2::{Digest, Sha256};
    const NAME: &str = "nn-c9e480e92425.nnue";
    const SHA256: &str = "c9e480e92425f887df6ab9b05c6180fbd762b07879df9d9845f1aa75440caa73";
    println!("cargo:rerun-if-changed={NAME}");
    let bytes = std::fs::read(NAME)
        .expect("Run python scripts/fetch_aster_network.py before building with embed-net");
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        SHA256,
        "The pinned Aster core network checksum does not match"
    );
}
