"""Read-only diagnosis and conservative repairs from existing application rules."""
from dataclasses import dataclass, field
import re

from cryostack_src.agents.intent import Proposal
from cryostack_src.models.workflow_capabilities import resolve_workflow_capabilities
from cryostack_src.resources.profiles import get_compute_profile
from icesee_jupyter_book.ui.shared_validation import (
    validate_slurm_resources, validate_remote_identity, validate_wall_time,
)

REMOTE_REVIEW_NOTE = "Remote identity and backend readiness must be verified before execution."


@dataclass
class RepairProposal(Proposal):
    suggested: list[str] = field(default_factory=list)


@dataclass
class Diagnosis:
    issues: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    proposal: RepairProposal = field(default_factory=RepairProposal)


def diagnosis_request(text):
    # Whole-request matching prevents ignoring appended scientific instructions.
    text = re.sub(r"[?!.,]+$", "", text.strip().lower().replace("’", "'"))
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^please ", "", text)
    if re.fullmatch(r"why (?:can't|can not|cannot) i run (?:this|this configuration)|what(?:'s| is) wrong with (?:my|this|the) configuration", text):
        return "diagnose"
    if re.fullmatch(r"fix (?:my|this|the) configuration|make (?:my|this|the) configuration runnable", text):
        return "repair"
    return None


def diagnose_configuration(data, findings):
    """Never mutate controls or claim execution readiness from partial checks.

    Findings come from the host's read-only checks. Resource checks and repair
    defaults use the same shared validator/profile as manual configuration.
    No scientific values, identities, licenses or compute choices are guessed.
    """
    result = Diagnosis()
    result.issues = list(dict.fromkeys(m for m in findings if m != REMOTE_REVIEW_NOTE))
    if REMOTE_REVIEW_NOTE in findings:
        result.notes.append(REMOTE_REVIEW_NOTE)
    current = data['current']
    example = next((e for e in data['examples'] if e['id'] == current.get('example')), None)
    if example is None:
        result.issues.append('Select a supported example in the existing controls.')
        return result
    model = example['model']
    if current.get('model', model) != model:
        result.issues.append('The selected model and example do not match. Choose the model or example you intend to use.')
    capabilities = resolve_workflow_capabilities(
        model='icesee' if data['application'] == 'icesee' else model,
        forecast_model=model)
    if capabilities.requires_matlab_license:
        result.notes.append('This workflow requires MATLAB licensing. Confirm its readiness through the existing review controls; Agent does not change licensing.')
    modes = [mode for mode in example.get('modes', data['modes']) if mode in data['modes']]
    if current.get('mode') not in modes:
        result.issues.append('Execution is not supported for this example. Choose an available location: ' + ', '.join(modes) + '.')
    for key, choices, label in (('filter', data.get('filters'), 'filter'),
                                ('backend', data.get('backends'), 'software backend')):
        if choices and current.get(key) not in choices:
            result.issues.append(f'Choose a supported {label}: ' + ', '.join(choices) + '.')
    changes = {}
    corrected = set()
    if current.get('mode') == 'remote':
        profile = get_compute_profile(current.get('profile'))
        args = dict(nodes=current.get('nodes'), tasks=current.get('cpus'),
                    tasks_per_node=current.get('tasks_per_node'),
                    wall_time=current.get('wall_time', ''), memory=current.get('memory', ''),
                    account=current.get('account', ''), account_required=profile.account_required)
        errors = validate_slurm_resources(**args)
        result.issues.extend(errors)
        result.issues.extend(validate_remote_identity(
            hpc_username=current.get('user', ''), remote_directory=current.get('directory', '')))
        # Only missing values with a declared default are repairable. An invalid
        # nonempty duration may express intent; replacing it would guess intent.
        default = profile.scheduler_defaults.wall_time
        if not args['wall_time'].strip() and default and validate_wall_time(default) is None:
            remaining = validate_slurm_resources(**dict(args, wall_time=default))
            corrected = set(errors) - set(remaining)
            if corrected:
                changes['wall_time'] = default
    result.issues = list(dict.fromkeys(result.issues))
    unresolved = [issue for issue in result.issues if issue not in corrected]
    if changes and not unresolved:
        result.proposal.values = dict(model=model, example=example['id'], **changes)
        result.proposal.retained = ['model', 'example']
        result.proposal.suggested = list(changes)
        result.proposal.reasons['wall_time'] = 'The selected resource supplies this default time limit for the missing value.'
    else:
        result.proposal.errors = list(result.issues)
    return result
