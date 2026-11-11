# frozen_string_literal: true

# Make the task board match board.yaml (docs/apps/openproject.md, "Board
# structure"). Run by Job openproject/openproject-board-structure with
# `bundle exec rails runner` in OpenProject's own image, like provision.rb: no
# admin API token, no Kubernetes API access, no secrets read or written.
#
# Idempotent. Each run ensures, in order:
#   1. the projects (private, under their parents);
#   2. the listed demo projects are archived;
#   3. the Needs Ryan status;
#   4. the agent role with exactly its permissions, and its workflows (a copy
#      of Member's, plus every transition into and out of Needs Ryan, for the
#      agent role, Member and Project admin);
#   5. the handoff custom fields, on every default type and every board project;
#   6. the listed users and every member's user, without tokens;
#   7. each listed member on exactly its projects' subtrees with the agent role,
#      and OFF every other project: a bot is never left on a project its line
#      does not name, Work above all;
#   8. Ryan as Project admin on every board project;
#   9. a check, as each member: OpenProject's own visibility equals its line in
#      board.yaml, or the whole run is rolled back.
# DRY_RUN=true runs all of it inside a transaction and rolls it back, so a
# review sees the real changes the run would make without making them.

require "psych"
require "securerandom"

$stdout.sync = true

def fail!(msg)
  $stderr.puts "structure: #{msg}"
  exit 1
end

def say(msg) = puts("structure: #{msg}")

BOARD = Psych.safe_load_file(ENV.fetch("BOARD_FILE", "/opt/board/board.yaml"))
DRY_RUN = ENV["DRY_RUN"].to_s == "true"
ACTOR = User.system
LOGIN_RE = /\A[a-z0-9][a-z0-9-]{0,39}\z/

def service!(result, what)
  return result.result if result.success?

  fail!("#{what}: #{result.errors.full_messages.join('; ')}")
end

# Fresh from the database: creating a sub-project moves its parent's nested-set
# bounds, so an object loaded earlier would miss the new child.
def subtree(project)
  project = Project.find(project.id)
  [project] + project.descendants.to_a
end

def run_board # rubocop:disable Metrics/AbcSize, Metrics/MethodLength, Metrics/CyclomaticComplexity, Metrics/PerceivedComplexity
  # --- 1. Projects
  projects = {}
  BOARD.fetch("projects").each do |spec|
    ident, name, parent_ident = spec.fetch("identifier"), spec.fetch("name"), spec["parent"]
    parent = parent_ident && (projects[parent_ident] || Project.find_by(identifier: parent_ident))
    fail!("project #{ident}: parent #{parent_ident} does not exist") if parent_ident && parent.nil?
    project = Project.find_by(identifier: ident)
    if project.nil?
      project = service!(
        Projects::CreateService.new(user: ACTOR).call(
          name: name, identifier: ident, public: false, workspace_type: "project", parent_id: parent&.id
        ),
        "create project #{ident}"
      )
      say "created project #{ident} (id #{project.id})"
    else
      changes = {}
      changes[:public] = false if project.public?
      changes[:parent_id] = parent&.id if project.parent_id != parent&.id
      unless changes.empty?
        service!(Projects::UpdateService.new(user: ACTOR, model: project).call(**changes), "update #{ident}")
        say "updated project #{ident}: #{changes.keys.join(', ')}"
      end
      fail!("project #{ident} is archived; unarchive it by hand first") unless project.active?
    end
    projects[ident] = project.reload
  end
  board_projects = projects.values.flat_map { |p| subtree(p) }.uniq

  # --- 2. Archive the demo projects
  BOARD.fetch("archive", []).each do |ident|
    project = Project.find_by(identifier: ident)
    next if project.nil? || !project.active?

    service!(Projects::ArchiveService.new(user: ACTOR, model: project).call, "archive #{ident}")
    say "archived project #{ident}"
  end

  # --- 3. The Needs Ryan status
  needs_name = BOARD.fetch("needs_ryan_status")
  needs = Status.find_by(name: needs_name)
  if needs.nil?
    needs = Status.create!(name: needs_name, is_closed: false, position: (Status.maximum(:position) || 0) + 1)
    say "created status #{needs_name} (id #{needs.id})"
  elsif needs.is_closed
    fail!("status #{needs_name} exists but is closed; fix it by hand")
  end

  # --- 4. The agent role and its workflows
  wanted = BOARD.fetch("agent_permissions").map(&:to_sym)
  known = OpenProject::AccessControl.permissions.map(&:name)
  unknown = wanted - known
  fail!("unknown permissions in board.yaml: #{unknown.join(', ')}") unless unknown.empty?
  role_name = BOARD.fetch("agent_role")
  agent = ProjectRole.find_by(name: role_name)
  if agent.nil?
    agent = ProjectRole.create!(name: role_name, permissions: wanted)
    say "created role #{role_name} (id #{agent.id})"
  elsif agent.permissions.sort != wanted.sort
    extra = agent.permissions - wanted
    agent.permissions = wanted
    agent.save!
    say "reset role #{role_name}'s permissions#{extra.empty? ? '' : " (removed #{extra.join(', ')})"}"
  end
  member_role = ProjectRole.find_by(name: "Member") || fail!("no Member role to copy workflows from")
  admin_role = ProjectRole.find_by(name: BOARD.fetch("ryan_role")) || fail!("no #{BOARD['ryan_role']} role")
  copied = 0
  Workflow.where(role_id: member_role.id).find_each do |w|
    row = { role_id: agent.id, type_variant_id: w.type_variant_id, old_status_id: w.old_status_id,
            new_status_id: w.new_status_id, assignee: w.assignee, author: w.author }
    next if Workflow.exists?(row)

    Workflow.create!(row)
    copied += 1
  end
  say "copied #{copied} workflow transitions from Member to #{role_name}" if copied.positive?
  variants = TypeVariant.where(project_id: nil)
  added = 0
  [agent, member_role, admin_role].each do |role|
    variants.each do |variant|
      Status.where.not(id: needs.id).find_each do |status|
        [[status.id, needs.id], [needs.id, status.id]].each do |old_id, new_id|
          # Every way out of Needs Ryan is allowed; a closed item does not
          # reopen straight into it.
          next if status.is_closed && new_id == needs.id

          row = { role_id: role.id, type_variant_id: variant.id, old_status_id: old_id,
                  new_status_id: new_id, assignee: false, author: false }
          next if Workflow.exists?(row)

          Workflow.create!(row)
          added += 1
        end
      end
    end
  end
  say "added #{added} workflow transitions for #{needs_name}" if added.positive?

  # --- 5. The handoff fields
  required = BOARD.fetch("fields_required") == true
  BOARD.fetch("fields").each do |spec|
    name, max = spec.fetch("name"), spec.fetch("max_length")
    field = WorkPackageCustomField.find_by(name: name)
    if field.nil?
      field = WorkPackageCustomField.create!(
        name: name, field_format: "string", is_required: required, max_length: max,
        is_for_all: false, searchable: true
      )
      say "created custom field #{name} (id #{field.id})"
    else
      fail!("custom field #{name} exists as #{field.field_format}, not string") unless field.field_format == "string"
      if field.is_required != required || field.max_length != max
        field.update!(is_required: required, max_length: max)
        say "updated custom field #{name}: required=#{required} max_length=#{max}"
      end
    end
    missing_variants = variants.reject { |v| field.type_variants.include?(v) }
    field.type_variants << missing_variants unless missing_variants.empty?
    missing_projects = board_projects.reject { |p| field.projects.include?(p) }
    field.projects << missing_projects unless missing_projects.empty?
    unless missing_variants.empty? && missing_projects.empty?
      say "custom field #{name}: +#{missing_variants.size} types, +#{missing_projects.size} projects"
    end
  end

  # --- 6. Users: the listed ones and every member, without tokens (the
  # provisioner issues those). Creating members here keeps the order free:
  # whichever runs first, both converge.
  displays = BOARD.fetch("users", []).to_h { |u| [u.fetch("login"), u.fetch("display")] }
  (displays.keys | BOARD.fetch("members").keys).each do |login|
    spec = { "display" => displays.fetch(login, login.split("-").map(&:capitalize).join(" ")) }
    fail!("user login #{login.inspect} is not allowed") unless login.match?(LOGIN_RE)
    user = User.find_by(login: login)
    if user.nil?
      password = "#{SecureRandom.alphanumeric(32)}aA1!"
      user = service!(
        Users::CreateService.new(user: ACTOR).call(
          login: login, firstname: spec.fetch("display"), lastname: "(bot)", mail: "#{login}@agents.invalid",
          admin: false, status: User.statuses[:active], password: password, password_confirmation: password
        ),
        "create user #{login}"
      )
      say "created user #{login} (id #{user.id})"
    elsif user.admin?
      fail!("user #{login} is an admin; an agent's account must not be. Fix it by hand")
    end
  end

  # --- 7. Members: exactly their projects, and nothing else
  allowed_by_login = {}
  BOARD.fetch("members").each do |login, idents|
    fail!("member login #{login.inspect} is not allowed") unless login.match?(LOGIN_RE)
    user = User.find_by(login: login)
    fail!("user #{login} is missing after step 6") if user.nil?
    fail!("user #{login} is an admin; refusing to manage its memberships") if user.admin?
    allowed = idents.flat_map do |ident|
      project = projects[ident] || fail!("member #{login}: #{ident} is not a board project")
      subtree(project)
    end.uniq
    allowed_by_login[login] = allowed
    allowed.each do |project|
      member = Member.find_by(project_id: project.id, user_id: user.id)
      if member.nil?
        service!(
          Members::CreateService.new(user: ACTOR).call(project: project, principal: user, role_ids: [agent.id]),
          "add #{login} to #{project.identifier}"
        )
        say "added #{login} to #{project.identifier} as #{role_name}"
      elsif member.role_ids.sort != [agent.id]
        service!(
          Members::UpdateService.new(user: ACTOR, model: member).call(role_ids: [agent.id]),
          "set #{login}'s role in #{project.identifier}"
        )
        say "set #{login}'s role in #{project.identifier} to #{role_name}"
      end
    end
    Member.where(user_id: user.id).where.not(project_id: allowed.map(&:id)).where.not(project_id: nil).find_each do |member|
      service!(Members::DeleteService.new(user: ACTOR, model: member).call, "remove #{login} from #{member.project_id}")
      say "removed #{login} from project #{member.project&.identifier || member.project_id}"
    end
  end

  # --- 8. Ryan
  ryan = User.find_by(id: BOARD.fetch("ryan_user_id")) || fail!("no user id #{BOARD['ryan_user_id']} for Ryan")
  board_projects.each do |project|
    member = Member.find_by(project_id: project.id, user_id: ryan.id)
    next if member && member.role_ids.include?(admin_role.id)

    if member
      service!(
        Members::UpdateService.new(user: ACTOR, model: member).call(role_ids: (member.role_ids + [admin_role.id]).uniq),
        "make Ryan admin of #{project.identifier}"
      )
    else
      service!(
        Members::CreateService.new(user: ACTOR).call(project: project, principal: ryan, role_ids: [admin_role.id]),
        "add Ryan to #{project.identifier}"
      )
    end
    say "Ryan is #{admin_role.name} of #{project.identifier}"
  end

  # --- 9. Check: what OpenProject itself lets each member see is exactly its
  # line in board.yaml. A public project, a stray membership or a group would
  # show up here, and the whole run is rolled back.
  allowed_by_login.each do |login, allowed|
    user = User.find_by!(login: login)
    seen = Project.visible(user).where(active: true).pluck(:identifier).sort
    expected = allowed.map(&:identifier).sort
    fail!("#{login} can see #{seen.join(', ')}, not #{expected.join(', ')}") unless seen == expected
  end
  say "checked: every member sees exactly its projects"

  public_board = board_projects.select(&:public?)
  fail!("board projects still public: #{public_board.map(&:identifier).join(', ')}") unless public_board.empty?
  say "done: #{board_projects.size} board projects, #{BOARD['members'].size} members listed"
end

if DRY_RUN
  ActiveRecord::Base.transaction do
    run_board
    say "DRY_RUN: rolling everything back"
    raise ActiveRecord::Rollback
  end
else
  ActiveRecord::Base.transaction { run_board }
end
