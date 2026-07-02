# The dispatcher stack's shared data: the S3 store bucket the dispatching Lambda writes
# status markers to. The synthesizer Lambda it async-invokes lives in its own
# stack (`./synthesizer/`), referenced by its deterministic derived name -- see lambda.tf.

locals {
  store_bucket = data.terraform_remote_state.storage.outputs.bucket_name
}
