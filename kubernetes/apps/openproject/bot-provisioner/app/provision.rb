# frozen_string_literal: true

# Provision one Hermes bot on the OpenProject task board (docs/openproject.md,
# "Bot provisioning"). Run by Job openproject/hermes-provision-<bot> with
# `bundle exec rails runner`, inside OpenProject's own image, so it uses
# OpenProject's services and contracts the way its seeder does. No admin API
# token is involved: the runner talks to the database as the app.
#
# Idempotent. Each run:
#   0. Checks BOT_NAME, the bot's namespace and Secret name, and the Secret's
#      provisioner labels; refuses otherwise.
#   1. Exits early when the bot's TASK_BOARD_ENABLED is not "true".
#   2. Ensures user <bot>: active, never an admin (an existing admin account
#      of that login is refused, not demoted).
#   3. Ensures project BOARD_PROJECT exists, and that the bot (role
#      BOT_ROLE) and Ryan (RYAN_USER_ID, role RYAN_ROLE) are members.
#   4. Keeps the token in the bot's Secret when OpenProject still accepts it
#      for that user; otherwise deletes this provisioner's earlier tokens for
#      the bot, creates a new one and merge-patches it into the Secret.
# The token value is never printed.

require "base64"
require "json"
require "net/http"
require "openssl"
require "securerandom"

$stdout.sync = true

# $stderr.puts, not warn: OpenProject loads StructuredWarnings, which takes
# over Kernel#warn, and the message never reaches the pod log.
def fail!(msg)
  $stderr.puts "provision: #{msg}"
  exit 1
end

def env!(name)
  value = ENV[name].to_s
  fail!("#{name} is not set") if value.empty?
  value
end

BOT = env!("BOT_NAME")
NAMESPACE = env!("BOT_NAMESPACE")
SECRET = env!("SECRET_NAME")
PROJECT_ID = env!("BOARD_PROJECT")
PROJECT_NAME = env!("BOARD_PROJECT_NAME")
BOT_ROLE = env!("BOT_ROLE")
RYAN_ROLE = env!("RYAN_ROLE")
# "task_board=<true|false> ryan_user_id=<id>": one string, so substitution
# can't turn a value into a YAML bool or int (template/job.yaml).
INPUTS = env!("BOT_INPUTS").split.map { |pair| pair.split("=", 2) }.to_h
TASK_BOARD_ENABLED = INPUTS["task_board"].to_s
fail!("BOT_INPUTS ryan_user_id must be a number") unless INPUTS["ryan_user_id"].to_s.match?(/\A[1-9][0-9]*\z/)
RYAN_USER_ID = INPUTS["ryan_user_id"].to_i
TOKEN_NAME = "hermes (k8s-gitops provisioner)"
LABEL_NAME = "openproject-bot-provisioner"

fail!("BOT_NAME must be lowercase letters, digits and -, at most 40") unless BOT.match?(/\A[a-z0-9][a-z0-9-]{0,39}\z/)
fail!("BOT_NAMESPACE must be hermes-#{BOT}") unless NAMESPACE == "hermes-#{BOT}"
fail!("SECRET_NAME must be hermes-#{BOT}-openproject") unless SECRET == "hermes-#{BOT}-openproject"

# --- Kubernetes API, as this Job's ServiceAccount (get/patch on SECRET only)
SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"

def kube(method, path, body = nil)
  uri = URI("https://kubernetes.default.svc#{path}")
  http = Net::HTTP.new(uri.host, uri.port)
  http.use_ssl = true
  http.ca_file = "#{SA_DIR}/ca.crt"
  http.verify_mode = OpenSSL::SSL::VERIFY_PEER
  http.open_timeout = 10
  http.read_timeout = 30
  req = method == :get ? Net::HTTP::Get.new(uri) : Net::HTTP::Patch.new(uri)
  req["Authorization"] = "Bearer #{File.read("#{SA_DIR}/token").strip}"
  req["Accept"] = "application/json"
  if body
    req["Content-Type"] = "application/merge-patch+json"
    req.body = JSON.generate(body)
  end
  res = http.request(req)
  fail!("#{method.upcase} #{path}: HTTP #{res.code}") unless res.is_a?(Net::HTTPSuccess)
  JSON.parse(res.body)
end

secret_path = "/api/v1/namespaces/#{NAMESPACE}/secrets/#{SECRET}"
secret = kube(:get, secret_path)
labels = secret.dig("metadata", "labels") || {}
unless labels["app.kubernetes.io/name"] == LABEL_NAME && labels["app.kubernetes.io/instance"] == BOT
  fail!("Secret #{NAMESPACE}/#{SECRET} lacks the provisioner labels for #{BOT}; not touching it")
end

if TASK_BOARD_ENABLED != "true"
  puts "provision: #{BOT} has TASK_BOARD_ENABLED=#{TASK_BOARD_ENABLED.inspect}; nothing to do"
  exit 0
end

def service!(result, what)
  return result.result if result.success?

  fail!("#{what}: #{result.errors.full_messages.join('; ')}")
end

actor = User.system

# --- 2. The bot's user
user = User.find_by(login: BOT)
if user.nil?
  password = "#{SecureRandom.alphanumeric(32)}aA1!"
  user = service!(
    Users::CreateService.new(user: actor).call(
      login: BOT,
      firstname: BOT.capitalize,
      lastname: "(bot)",
      mail: "#{BOT}@hermes.invalid",
      admin: false,
      status: User.statuses[:active],
      password: password,
      password_confirmation: password
    ),
    "create user #{BOT}"
  )
  puts "provision: created user #{BOT} (id #{user.id})"
else
  fail!("user #{BOT} is an admin; a bot's account must not be. Fix it by hand") if user.admin?
  fail!("user #{BOT} is not a regular user (#{user.class.name})") unless user.is_a?(User) && user.instance_of?(User)
  unless user.active?
    user.update!(status: User.statuses[:active])
    puts "provision: re-activated user #{BOT}"
  end
end

# --- 3. The board project and memberships
project = Project.find_by(identifier: PROJECT_ID)
if project.nil?
  project = service!(
    # OpenProject 17 requires a workspace type (project, program or portfolio).
    Projects::CreateService.new(user: actor).call(
      name: PROJECT_NAME, identifier: PROJECT_ID, public: false, workspace_type: "project"
    ),
    "create project #{PROJECT_ID}"
  )
  puts "provision: created project #{PROJECT_ID} (id #{project.id})"
end

def ensure_member(actor, project, principal, role_name)
  role = ProjectRole.find_by(name: role_name)
  fail!("no project role named #{role_name.inspect}") if role.nil?
  member = Member.find_by(project_id: project.id, user_id: principal.id)
  if member.nil?
    service!(
      Members::CreateService.new(user: actor).call(project: project, principal: principal, role_ids: [role.id]),
      "add #{principal.login} to #{project.identifier}"
    )
    puts "provision: added #{principal.login} to #{project.identifier} as #{role_name}"
  elsif !member.roles.include?(role)
    puts "provision: #{principal.login} is in #{project.identifier} with #{member.roles.map(&:name).join(', ')}; left as is"
  end
end

ensure_member(actor, project, user, BOT_ROLE)
ryan = User.find_by(id: RYAN_USER_ID)
if ryan.nil?
  puts "provision: no user id #{RYAN_USER_ID}; Ryan not added to #{PROJECT_ID}"
else
  ensure_member(actor, project, ryan, RYAN_ROLE)
end

# --- 4. The bot's API token
data = secret["data"] || {}
current = data["OPENPROJECT_API_TOKEN"] ? Base64.decode64(data["OPENPROJECT_API_TOKEN"]) : ""
existing = current.empty? ? nil : Token::API.find_by_plaintext_value(current)

if existing && existing.user_id == user.id
  puts "provision: #{BOT}'s token in #{NAMESPACE}/#{SECRET} is still valid"
else
  Token::API.where(user_id: user.id).select { |t| t.token_name == TOKEN_NAME }.each(&:destroy!)
  token = service!(
    APITokens::CreateService.new(user: user, model: Token::API.new).call(token_name: TOKEN_NAME),
    "create API token for #{BOT}"
  )
  current = token.plain_value.to_s
  fail!("token service returned no value") if current.empty?
  puts "provision: issued a new API token for #{BOT}"
end

patch = {
  "OPENPROJECT_API_TOKEN" => current,
  "OPENPROJECT_USER" => BOT,
  "OPENPROJECT_USER_ID" => user.id.to_s,
  "OPENPROJECT_PROJECT" => PROJECT_ID
}
kube(:patch, secret_path, { "data" => patch.transform_values { |v| Base64.strict_encode64(v) } })
puts "provision: #{NAMESPACE}/#{SECRET} up to date (user #{BOT}, id #{user.id}, project #{PROJECT_ID})"
