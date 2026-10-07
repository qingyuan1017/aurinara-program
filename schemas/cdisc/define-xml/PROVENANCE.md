# Define-XML schema provenance

These files are pinned repository assets. Runtime code and tests do not download schemas.

- `2.1/`, `cdisc-odm-1.3.2/`, and `core/` are unchanged files from
  `cdisc-org/DataExchange-RWD-Lineage` commit
  `ff3c2fee622b69035526c9bf507d02d59e351a0e`. That public CDISC repository describes code as
  MIT licensed and content as CC-BY-4.0. Its Define 2.1 extension permits the optional public
  RWD-lineage namespace; Aurinara does not emit that extension.
- `2.0/` is unchanged from `dbosak01/defineR` commit
  `d4d5dc4bab76f65dc905267634d743c93d0c0f07`, whose package metadata declares CC0.

The schemas provide XSD conformance checks only. Their inclusion does not claim regulatory
certification or parity with a commercial validator.

## SHA-256

```text
643ad7aaefa0bba45df1b4fb7a4c4cb57c719e32af1d407c5bd98d193e31c3ff  2.0/define-extension.xsd
6ebc4c41917f166ced33f9b495158ef2907fe1b9ccfe007ffb392d773f1585c6  2.0/define-ns.xsd
ead6b6d2cc6aadfd7a0adf885bd3b89f680af7e3892c7034a052e8b7d3fa04b5  2.0/define2-0-0.xsd
de9b57299747269260f548f6fef0c2e86413d1dec8a8c41907b79b93189460b0  2.1/define-enumerations.xsd
f0c53e96b79edcf754c3cc8569744850587212ec278d170a0158a3fe1925efcd  2.1/define-extension.xsd
401cd03fb3d61e5554c2c995a789223842968fb372a93197e57d18780b1bdb33  2.1/define-ns.xsd
368794dba37dd8e3ff67eec0e3a3240c7c9888e66a89775215454b69c31100ab  2.1/define2-1-0.xsd
3edb7009d5db5c501afa60c50051408e56b065722314d279ecb78284e9852391  2.1/rwd-lineage.xsd
e8e647e482ed29f7e02b50fbcaa1452a362bc8c8419facc31aefb871464507f9  cdisc-odm-1.3.2/ODM1-3-2-foundation.xsd
f9adc41cf2b041b40354f685e8e5458105e89e76827622fa071b7edf817de37a  cdisc-odm-1.3.2/ODM1-3-2.xsd
ecf6c8e105afe431c93a8026365a15cf4c37d15a8d0f02d85d4870099ecfb1ee  cdisc-odm-1.3.2/xlink.xsd
181374970cc73d2edf7a91af276d2777a898a85fc5d036af658d02ef3fc1e52b  cdisc-odm-1.3.2/xml.xsd
b234233e70724c5a1a768a2cf2cd6c9884a5a886e3f0fc9178991536ae0c357d  cdisc-odm-1.3.2/xmldsig-core-schema.xsd
ecf6c8e105afe431c93a8026365a15cf4c37d15a8d0f02d85d4870099ecfb1ee  core/xlink.xsd
181374970cc73d2edf7a91af276d2777a898a85fc5d036af658d02ef3fc1e52b  core/xml.xsd
b234233e70724c5a1a768a2cf2cd6c9884a5a886e3f0fc9178991536ae0c357d  core/xmldsig-core-schema.xsd
```
