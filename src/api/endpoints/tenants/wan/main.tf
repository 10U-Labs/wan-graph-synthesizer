locals {
  store_bucket = data.terraform_remote_state.storage.outputs.bucket_name
}
