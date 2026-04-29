// Build script for generating Rust code from Protocol Buffers definitions

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Tell Cargo to re-run this build script if proto files change
    println!("cargo:rerun-if-changed=proto/schema.proto");

    // Compile the proto file
    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        .out_dir("src/generated")
        .compile(&["proto/schema.proto"], &["proto"])?;

    println!("Proto compilation completed successfully");
    
    Ok(())
}
