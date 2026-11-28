# Ensures OpenProject's outgoing webhook for the bots' task board: task
# changes in the board project go to openproject-mcp's relay, which wakes the
# bot they are for (docs/apps/openproject.md, "Waking a bot"). Run with
# `bundle exec rails runner` in OpenProject's image (webhook-job.yaml).
#
# Idempotent: it finds the webhook by name, sets every field to what git
# says, and drops any duplicate of that name. Other webhooks are left alone.
# The signing key is never printed.
$stdout.sync = true

# $stderr.puts, not warn: OpenProject loads StructuredWarnings, which takes
# over Kernel#warn, and the message never reaches the pod log.
def fail!(msg)
  $stderr.puts "webhook: #{msg}"
  exit 1
end

def env!(name)
  value = ENV.fetch(name, "").strip
  fail!("#{name} is empty") if value.empty?
  value
end

NAME = env!("WEBHOOK_NAME")
URL = env!("WEBHOOK_URL")
PROJECT_ID = env!("BOARD_PROJECT")
SECRET = env!("OPENPROJECT_WEBHOOK_SECRET")
# A comment arrives as work_package:updated too (one event per journal), so
# these two cover assignments, edits, status changes and comments.
EVENTS = %w[work_package:created work_package:updated].freeze

project = Project.find_by(identifier: PROJECT_ID)
# The bots' provisioning Job creates the project; this Job retries until then.
fail!("project #{PROJECT_ID} does not exist yet") unless project

hooks = Webhooks::Webhook.where("lower(name) = ?", NAME.downcase).to_a
hook = hooks.shift || Webhooks::Webhook.new_default
hooks.each do |dup|
  dup.destroy!
  puts "webhook: removed duplicate id #{dup.id}"
end
created = hook.new_record?

result = Webhooks::Outgoing::UpdateWebhookService.new(hook, current_user: User.system).call(
  attributes: {
    name: NAME,
    description: "Wakes the Hermes bots on task changes (k8s-gitops, docs/apps/openproject.md). " \
                 "Managed by git: edits here are overwritten.",
    url: URL,
    secret: SECRET,
    enabled: true,
    project_ids: "selected",
    selected_project_ids: [project.id],
    events: EVENTS
  }
)
fail!("could not save: #{result.errors.full_messages.join('; ')}") unless result.success?

hook = result.result.reload
puts "webhook #{hook.name} (id #{hook.id}): #{created ? 'created' : 'updated'}; " \
     "url #{hook.url}; project #{PROJECT_ID}; events #{hook.event_names.sort.join(', ')}; " \
     "signed #{hook.secret.present?}"
