resource "remote_file" "scripts-precommit-add_container_images" {
  provider    = remote
  path        = "/config/scripts/commit/pre-hooks.d/add-container-images"
  content     = file(pathexpand("${path.root}/scripts/commit/pre-hooks.d/add-container-images"))
  permissions = "0775"
  owner       = "0"
  group       = "104"
}
