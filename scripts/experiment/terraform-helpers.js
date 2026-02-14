const { execSync } = require('child_process')

/**
 * Get Terraform outputs from an infrastructure directory, unwrapping values
 * @param {string} infraDir - Path to infrastructure directory
 * @returns {Object|null} Unwrapped Terraform outputs, or null on error
 */
function getTerraformOutputs (infraDir) {
  try {
    const output = execSync('terraform output -json', {
      cwd: infraDir,
      encoding: 'utf8'
    })
    const outputs = JSON.parse(output)
    const result = {}
    for (const [key, val] of Object.entries(outputs)) {
      result[key] = val.value
    }
    return result
  } catch (error) {
    console.log(`Could not get Terraform outputs from ${infraDir}: ${error.message}`)
    return null
  }
}

module.exports = { getTerraformOutputs }
