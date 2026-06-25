def pre_mutation(context):
    if "_LOGGER" in context.current_source_line:
        context.skip = True
